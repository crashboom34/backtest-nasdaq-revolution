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

*Note additive (2026-10-12) : la Décision 23 (23.13, 23.22) précise cet événement canonique — champs optionnels,
hash stocké, identifiant et nom de fichier déterministes, écriture exclusive durable ; le timing défini ici est
conservé.*

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
  de l'autorité »). Un claim ajouté à la main (finding 15) est donc refusé fermé. **Précision (D2,
  2026-10-07)** : « constructeur » désigne le **builder public validé** et les **chemins de reconstruction
  supportés** (`from_record`, validateurs) ; l'instanciation Python directe de la dataclass n'est pas une
  API de création validée (même discipline que `GateVCampaignPlanV2`), elle ne revalide rien.
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
**Précision (D4, 2026-10-10) — format exact de la sentinelle** : constante
`GATE_V_TECHNICAL_FAILURE_SENTINEL_SEMANTICS_VERSION = "gate_v_technical_failure_sentinel_v1"` ; objet JSON à
**exactement trois** clés de premier niveau : `technical_failure_sentinel_semantics_version` (égale à cette
constante), `campaign_id` (égal au `campaign_id` du Plan V2) et `reason` (chaîne non vide, encodable en UTF-8 :
vérifié AVANT la création exclusive). Aucun horodatage, PID, nom d'hôte, chemin ni révision. Une sentinelle n'est
**lisible et valide** que si ces trois conditions et cet ensemble exact de clés sont satisfaits ; toute autre forme
(vide, tronquée, illisible, version ou campagne différente, clé manquante ou en trop, motif vide ou non
encodable) reste un fait d'échec, réconcilié avec la chaîne fixe ci-dessous. Cette chaîne fixe est **réservée à la réconciliation** d'une
sentinelle existante illisible : aucune sentinelle n'est créée avec elle, ni pour un Manifest déjà marqué (son
premier motif ne change jamais). La sentinelle n'est **pas** un Claim.
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

## Décision 22 — `FinalHoldoutAccessClaim` : cœur pur et acquisition exclusive (Slice E, 2026-10-11)

**Statut au 2026-10-11** : **E1 = IMPLEMENTED + TESTED localement, NON COMMITTED** ; **E2 = SPECIFIED, NOT
IMPLEMENTED** ; **E3 = DESIGN NOT LOCKED**. `GATE V` NON PASSÉE, `FINAL_HOLDOUT` NON ACCÉDÉ **par `AF-V-07`** (un accès antérieur et distinct est documenté
dans `DOMAIN_MODEL.md` §12 ; **aucune fraîcheur de holdout n'est établie par cette Décision**, voir 22.2).

**Portée de cette Décision** : elle précise, sans les contredire, les Décisions 9 (primitif exclusif), 10
(identité et hash du Claim), 11 (acquisition, course, crash), 13 (extension additive de `HoldoutAccessEvent`
et du Manifest), 20 (canonicalisation, Plan V2) et 21 (Manifest V2, précondition 21.7, verrou 21.8). **Les
formules de `claim_id` et de `claim_content_hash` sont exclusivement celles de la Décision 10 ; aucune
seconde définition n'existe ici ni ne doit exister dans le code.** Aucune formule d'identité ou de hash
historique n'est modifiée.

### 22.1 — Découpage et périmètre

- **E1** — `gate_v_final_holdout_claim.py` : cœur **pur**, aucune E/S, aucune horloge, aucun accès marché,
  aucun appel moteur. Dépendances : bibliothèque standard (`hashlib`, `json`, `re`, `dataclasses`,
  `datetime`) et `gate_v_campaign_plan_v2` uniquement. Il ne modifie aucun module existant ; aucun module
  existant ne l'importe.
- **E2** — `gate_v_final_holdout_claim_acquisition.py` : acquisition exclusive durable et chargeur d'audit en
  lecture seule. Elle ne modifie qu'**un** fichier existant, `atomic_json_store.py` (22.8, strictement
  additif).
- **E3** — `run_gate_v_final_holdout_validation` (Décision 13) : **hors Slice E, design non verrouillé.**
  Seules les obligations de 22.12 le lient.
- **Interdits en Slice E** : toute lecture de `FINAL_HOLDOUT` ou de donnée de marché ; tout appel à
  `run_oos_validation` ou au moteur ; tout `HoldoutAccessEvent` ; toute écriture des champs 13-17 du Manifest ;
  toute modification du Plan V2, du Manifest, de V1 ou de `validation_oos` ; toute suppression, tout
  renommage, toute réparation ou réécriture d'un Claim, d'un verrou ou d'une sentinelle.
- **Instancier un `FinalHoldoutAccessClaim` n'autorise rien** : l'autorité d'exclusivité est la création
  exclusive du fichier (Décision 9), jamais l'objet en mémoire (cf. 21.10).

### 22.2 — Portée de l'exclusivité et contrôle d'exposition obligatoire avant E3

L'exclusivité est **par campagne** : un seul Claim valide existe par `campaign_id`. **Elle ne prouve aucune
fraîcheur de la donnée `FINAL_HOLDOUT`.** Un registre transversal n'est volontairement pas introduit en E1/E2.

Les artefacts V2 ne relient pas les campagnes entre elles :
- un autre `ResearchRun`, une autre stratégie, un autre `split_plan_id` ou un autre snapshot produit un autre
  scope, donc une autre campagne et un autre Claim ;
- `validation_oos` ne limite pas le nombre d'accès ;
- une même période calendaire peut avoir été exposée sous des identifiants différents, ou par des exécutions
  jamais enregistrées (précédents documentés : `DOMAIN_MODEL.md` §12, `GATE DATA` et AF-V-01).

**L'absence de `HoldoutAccessEvent`, de Claim ou de campagne n'est jamais une preuve que le holdout est
vierge** (`DOMAIN_MODEL.md` §18 point 7). `has_holdout_access_events()` n'établit qu'un constat factuel sur
un répertoire d'audit donné.

**Contrôle d'exposition du holdout** — artefact à spécifier avant E3, hors Slice E. Exigences minimales :
1. Il s'exécute **avant** la séquence d'acquisition (Décision 11) : le Claim consomme le droit de façon
   irréversible, la vérification doit donc le précéder.
2. Il est lié à `campaign_id`, `dataset_snapshot_id`, `split_plan_id` et `split_plan_fingerprint`.
3. Il énumère les expositions par **données et fenêtre calendaire** (comparaison de bornes avec fuseau), pas
   seulement par identifiant :
   - tous les `HoldoutAccessEvent` de tout plan partageant le snapshot ou chevauchant la fenêtre ;
   - tous les Claims et campagnes V2 connus, les campagnes V1 avec OOS et les `ValidationRun` de type OOS ;
   - les snapshots distincts couvrant la même période de marché.
4. Tout artefact illisible ou invalide d'un répertoire d'audit est un **échec**, jamais ignoré
   (`list_holdout_access_events()` ignore silencieusement les JSON invalides : elle ne peut pas seule fonder
   ce contrôle).
5. Les expositions non enregistrées (scripts, notebooks, grands livres de trades) et les décisions humaines
   prises après exposition sont **déclarées par attestation humaine nominative**.
6. Il enregistre le nombre de stratégies, de `ResearchRun` et de campagnes évalués contre ce holdout
   (comptabilité de multiple testing ; la correction statistique elle-même est hors périmètre).
7. Il classe dans un ensemble fermé : `FRESH_UNEXPOSED_DECLARED`, `RETROSPECTIVE_EXPOSED`, `UNDETERMINED`.
   `FRESH_UNEXPOSED_DECLARED` est une **déclaration**, jamais une preuve.
8. Il est immuable (création exclusive) et son hash est référencé par l'artefact d'audit d'E3. Le porteur exact
   (champ additionnel de l'événement canonique, ce qui exigerait un amendement additif de la Décision 13, ou
   artefact distinct) reste à spécifier avec E3. Le schéma du Claim (22.3) ne le porte pas.

E2 n'applique pas ce contrôle ; il relève d'E3 (22.12).

### 22.3 — Schéma du Claim : 14 clés exactes, aucune autre

Fichier : `<campaign_dir>/final_holdout_access_claim.json` (Décision 10). Toutes les valeurs sont des `str`
JSON (type exact : ni booléen, ni nombre, ni `null`, ni sous-classe de `str`), non vides.

| # | Clé | Contrainte | Provenance |
|---|---|---|---|
| 1 | `claim_semantics_version` | `== "final_holdout_access_claim_v1"` | constante `FINAL_HOLDOUT_ACCESS_CLAIM_SEMANTICS_VERSION` |
| 2 | `claim_id` | SHA-256 hex minuscule, 64 car. | Décision 10 |
| 3 | `claim_content_hash` | SHA-256 hex minuscule, 64 car. | Décision 10 (hors de sa propre préimage) |
| 4 | `campaign_id` | `gate_v_v2_` + 64 hex minuscules | Plan V2 |
| 5 | `preregistration_id` | hex64 | Plan V2 |
| 6 | `preregistration_content_hash` | hex64 | Plan V2 |
| 7 | `campaign_protocol_fingerprint` | hex64 | Plan V2 |
| 8 | `research_run_id` | str non vide | Plan V2 |
| 9 | `research_run_content_hash` | hex64 | Plan V2 |
| 10 | `dataset_snapshot_id` | str non vide | Plan V2 |
| 11 | `split_plan_id` | str non vide | Plan V2 |
| 12 | `split_plan_fingerprint` | hex64 | Plan V2 |
| 13 | `assessment_semantics_version` | str non vide | Plan V2 |
| 14 | `created_at` | format exact ci-dessous, **hors des deux hashes** | argument explicite |

Les clés 4 à 13 sont toutes déjà portées par `GateVCampaignPlanV2` : le Claim est une **projection pure du
plan**, plus `created_at`. `policy_git_sha` et les identités de policy n'y figurent pas et restent
transitifs via `preregistration_id`. **La Décision 10 fixe la préimage des deux hashes ; le schéma à 14 clés
est fixé par la présente Décision.**

**Format exact de `created_at`** (E1 et ADR sont alignés) : instant ISO-8601 **avec fuseau explicite**,
conforme à l'expression `AAAA-MM-JJTHH:MM:SS[.f]` où la fraction `.f` compte de 1 à 6 chiffres et est
optionnelle, suivie de `Z` ou de `±HH:MM`. Séparateur `T` obligatoire ; secondes obligatoires ; chiffres
**ASCII** uniquement ; aucun espace ni saut de ligne en tête ou en queue. Sont **refusés** : l'absence de
fuseau, `±HHMM`, l'heure sans secondes, la date seule, un espace comme séparateur, un décalage hors plage
(par exemple `+24:00`), tout instant que `datetime.fromisoformat` refuse. La valeur est **conservée
verbatim** (jamais normalisée ni réécrite). Les lettres `T` et `Z` sont **majuscules** (`t` et `z` sont
refusés), une valeur composée d'espaces est refusée, et `Z` suppose Python 3.11 ou plus. **Limite connue (MINOR,
champ d'audit uniquement)** : la plage des décalages est celle que `datetime.fromisoformat` accepte ; E1 ne la
restreint pas davantage (par exemple `+00:60` est accepté). Exemples valides : `2026-10-11T10:00:00Z`,
`2026-10-11T10:00:00+00:00`, `2027-01-02T14:30:00.123456+02:00` ; la valeur par défaut d'E2
(`datetime.now(timezone.utc).isoformat()`) est conforme.

`created_at` est une métadonnée d'audit **non cryptographique** : il ne prouve pas la chronologie, une
modification du fichier ou de l'horloge système suffit à l'altérer. Il n'entre dans aucun hash.

### 22.4 — Contrat E1 (pur)

- Constante `FINAL_HOLDOUT_ACCESS_CLAIM_SEMANTICS_VERSION = "final_holdout_access_claim_v1"` ; dataclass
  `FinalHoldoutAccessClaim` immuable (`frozen`) à 14 champs dans l'ordre de 22.3.
- `compute_final_holdout_access_claim_id(*, <11 champs de la préimage>)` et
  `compute_final_holdout_access_claim_content_hash(*, claim_id, <11 champs de la préimage>)` appliquent la
  Décision 10 avec la canonicalisation de la Décision 20.3 (`sort_keys=True`, séparateurs compacts,
  `ensure_ascii=False`, `allow_nan=False`) ; ils refusent tout champ absent, vide ou non `str`.
- `build_final_holdout_access_claim(plan, *, created_at)` valide le plan
  (`validate_gate_v_campaign_plan_v2_structure`) et `created_at`, projette les 10 champs de liaison, calcule
  les deux hashes et revalide le résultat. `created_at` est **obligatoire** ; le builder ne lit aucune
  horloge. Mêmes entrées, même sortie.
- `validate_final_holdout_access_claim_structure(claim)` impose : type exact, 14 champs `str` non vides,
  version sémantique exacte, formes `campaign_id` et hex64, format de `created_at`, **recalcul des deux
  hashes** depuis la préimage. Un Claim auto-cohérent mais sans lien avec un plan est valide ici.
- `validate_final_holdout_access_claim_against_plan(claim, plan)` revalide la structure du Claim et celle du
  plan, puis exige l'égalité des 10 champs de liaison. **Tout chargement d'un Claim existant par E2 doit
  appeler cette fonction.** Elle ne vérifie aucune source (22.5).
- `final_holdout_access_claim_to_record(claim)` (14 clés, ordre normatif ; refuse un Claim invalide) et
  `final_holdout_access_claim_from_record(record)` (`dict` exact, clés exactement les 14, aucune tolérance,
  hashes recalculés).
- Erreurs : `ValueError` pour toute valeur invalide ; une erreur d'appel (argument obligatoire manquant ou
  inattendu, dont `created_at`) lève `TypeError` avant tout contrôle. La mention « déterministe » de la Décision 11 étape 5 s'entend
  **hors `created_at`**.

### 22.5 — Frontière de confiance des sources (contrat E2)

`validate_gate_v_campaign_plan_v2_sources` recalcule depuis les objets qu'on lui fournit : il prouve la
**cohérence**, pas la **provenance persistée**. Une `GateVPreRegistration` construite en mémoire, jamais
sauvegardée, pourrait contourner l'unicité « une policy par scope » (Décision 8). E2 **ne reçoit donc aucun
objet source** ; elle charge, avec les chargeurs stricts existants :
1. `plan` = `load_gate_v_campaign_plan_v2(<campaign_dir>/plan.json)`, avec `campaign_dir.name ==
   plan.campaign_id`.
2. `preregistration` = `load_gate_v_preregistration(preregistration_path)`. Le nom du fichier doit être
   exactement `<scope_key>.json` et l'agencement doit respecter la Décision 16 : `<campaign_dir>.parent.name ==
   "campaigns"` et `preregistration_path == <campaign_dir>.parent.parent / "preregistrations" /
   "<scope_key>.json"` (le répertoire `preregistrations/` est frère de `campaigns/`). La Décision 16 ne donnait
   cette disposition qu'à titre conceptuel ; la présente Décision en fait une règle contraignante d'E2, qui
   ancre la préenregistrement à son emplacement exclusif par scope.
3. `research_run` = `load_research_run(research_run_path)` ; `None` est un refus.
4. `split_plan` = `load_dataset_split_plan(split_plan_path, strict=True)` ; `None` **ou toute `ValueError`**
   (le mode strict ne rattrape que `TypeError` et `KeyError`) est un refus.
5. `policy` = `load_gate_v_validation_policy(policy_path)`.

Puis `validate_gate_v_campaign_plan_v2_sources(...)` est appelée **sans modification**.
- **Provenance** : le contenu des sources est ancré par les hashes pinnés dans la préenregistrement, elle-même
  épinglée par `plan.json` (`preregistration_id`, `preregistration_content_hash`).
- **Policy** : la provenance Git est historique (blob au `policy_git_sha` pinné, Décision 20.10). Le fichier de
  policy du working tree doit produire un hash égal à `policy_content_hash` ; sinon la précondition échoue
  **avant** toute création (conservateur).
- **Données de marché** : E2 ne vérifie pas le contenu du fichier de marché contre `dataset_snapshot_id`
  (22.12).

### 22.6 — Séquence E2 (Décisions 11 et 21.7, précisées)

Étapes 1 à 5 : aucune création ; leurs erreurs se propagent telles quelles (`ValueError`,
`GitProvenanceError`, `OSError`) et aucun fichier n'a été créé par l'appel.
1. Arguments valides ; chargement du plan (22.5-1).
2. Chargement et ancrage de la préenregistrement (22.5-2).
3. Chargement des autres sources (22.5-3 à 5).
4. `validate_gate_v_campaign_plan_v2_sources`.
5. `manifest_before = assert_gate_v_pre_holdout_evidence_complete(plan, campaign_dir)` : l'**unique** prédicat
   de la Décision 21.7 ; aucune version allégée n'existe.
6. L'horloge est lue **une seule fois** si `created_at is None`
   (`datetime.now(timezone.utc).isoformat()`) ; le Claim est construit par E1 et son record fixé.
7. **Aucun test d'existence préalable.** Création exclusive durable :
   `save_exclusive(path, record, kind=…, durable=True)`.
   - `FileExistsError` devient `FinalHoldoutClaimAlreadyConsumedError` ; le Claim existant n'est ni lu ni
     inspecté, sans retry.
   - `ExclusiveCreationIncompleteError` devient `FinalHoldoutClaimPostAcquisitionError`.
   - Toute autre `OSError` à l'ouverture se propage telle quelle : rien n'a été créé.
8. Relecture stricte (`from_record`), `against_plan`, et égalité du record relu avec le record voulu (sur le
   record parsé, jamais sur les octets : sous Windows le mode texte peut écrire `\r\n`).
8 bis. `manifest_after = assert_gate_v_pre_holdout_evidence_complete(...)` doit être **égal** à
   `manifest_before`. Cette étape est la revérification de la sentinelle et du verrou exigée « après
   l'acquisition du Claim et avant toute lecture de marché » (21.8, qui la désigne par « Décision 11, étape
   8 » ; la numérotation de 11 reste inchangée).
9. Retour du Claim, uniquement si 1 à 8 bis ont réussi.

Toute exception des étapes 8 et 8 bis lève `FinalHoldoutClaimPostAcquisitionError` (chaînée). **Après toute
exception d'E2, aucun accès au marché n'est autorisé.** Un Claim créé reste consommé pour toujours.

### 22.7 — État du fichier Claim

Le fichier existant n'est jamais classé « absent » : valide, vide, tronqué ou corrompu, il donne
`FinalHoldoutClaimAlreadyConsumedError` à l'acquisition. Le chargeur d'audit `load_final_holdout_access_claim(
plan, campaign_dir)` est en lecture seule : `FileNotFoundError` si absent, `ValueError` si invalide, jamais
`None`, aucune réparation ni suppression.

### 22.8 — Durabilité : `save_exclusive(path, data, kind, *, durable=False)`

- **`durable=False`** : comportement historique **identique**, exceptions comprises.
- **`durable=True`** :
  - avant toute création : le payload est encodé en UTF-8 (une erreur lève avant création) et, sous POSIX,
    une sonde `fsync` du répertoire parent est effectuée (un échec lève avant création) ;
  - création `os.open(O_CREAT|O_EXCL|O_WRONLY)` ;
  - écriture, `flush`, `os.fsync` du fichier, puis `fsync` du répertoire parent sous POSIX ;
  - toute exception après l'ouverture réussie lève `ExclusiveCreationIncompleteError(OSError)`, chaînée,
    descripteur fermé, **fichier jamais supprimé**.
- **Limites (à qualifier avant toute exécution réelle)** :
  - Windows : `fsync` appelle `FlushFileBuffers` sur le fichier ; la durabilité de l'entrée de répertoire
    repose sur le journal NTFS et n'est pas démontrable depuis Python ;
  - Linux local : garantie du noyau pour le fichier et le répertoire, sous réserve de l'absence de cache
    d'écriture matériel mensonger ;
  - volume bloc persistant OCI : **non qualifié** ; une qualification réelle est obligatoire avant usage ;
  - NFS, SMB, object-store : **non supportés**, sans détection automatique (Décision 9) ;
  - `fsync` ne garantit pas la survie à toutes les pannes matérielles.

### 22.9 — Retry et gouvernance

Une création ne se réessaie pas : si le chemin existe, la tentative échoue fermée. Aucun retry automatique
n'est autorisé après une exception d'E2. La récupération d'un Claim « consommé sans accès enregistré » est
une **décision humaine** (matrice de la Décision 11) dont le protocole reste à spécifier avant toute
exécution réelle. Une erreur transitoire (antivirus, lecture bloquée) après la création peut consommer le
droit sans accès marché : risque accepté.

### 22.10 — Concurrence : fenêtres résiduelles non fermables par E2

- Entre les étapes 5 et 7 : un changement du Manifest, une sentinelle ou un verrou est détecté à l'étape 8 bis ;
  le droit est consommé sans accès, ce qui est sûr.
- Entre le retour d'E2 et la lecture marché d'E3 : non fermable. E3 refait une vérification locale
  (sentinelle, verrou) immédiatement avant la lecture.
- Un écrivain hors API ou une suppression manuelle du Claim reste hors modèle de menace (Décision 11).

### 22.11 — Compatibilité

V1 est inchangé. Le Manifest garde ses champs 13-17 à `None` et n'importe pas les modules du Claim.
`classify_gate_v_campaign_dir` ignore le fichier Claim. Les cinq statuts V2 conservent leur sens. Le verrou
`manifest.update.lock` n'est pas un Claim (21.8).

### 22.12 — Obligations d'E3 (design non verrouillé)

1. Exécuter le contrôle d'exposition de 22.2 **avant** E2.
2. Appeler **lui-même** E2 ; ne jamais accepter un Claim fourni en argument, ni relu d'un fichier existant,
   comme autorisation.
3. Rester le seul importateur d'E2 (test AST) et le seul chemin vers `run_oos_validation` pour la voie V2
   (`run_oos_validation` reste publique : l'exclusivité tient à cette discipline, non à son type).
4. Vérifier le contenu des données de marché contre `dataset_snapshot_id` : **aucune lecture du fichier de
   marché avant la création du Claim** (Décision 2 : rien du `FINAL_HOLDOUT` avant l'étape 8), puis une
   vérification portant sur **les octets effectivement transmis au moteur** (même lecture, pas une relecture)
   avant toute exécution. L'ordonnancement exact est à verrouiller avec E3.
5. Refaire la vérification locale de 22.10.
6. Produire l'unique `HoldoutAccessEvent` canonique (Décision 13), écrire le miroir d'audit du Manifest
   (extension monotone) et traiter l'état « Claim consommé sans accès enregistré ». L'existence du Claim seule
   ne prouve pas qu'un accès a eu lieu ; un crash entre la lecture et l'événement est traité comme accédé.

*Note additive (2026-10-12) : la Décision 23 verrouille le contrat d'E3 et amende la portée de 22.12.4 (23.5) ;
22.12 reste la liste historique des obligations.*

### 22.13 — Tests exigés

- **E1 (démontrables par tests unitaires)** : 14 champs dans l'ordre ; version exacte ; vecteurs de hash
  littéraux calculés hors du code testé ; exclusion de `created_at` des deux hashes ; chaque champ de liaison
  modifie les deux hashes ; rejet de toute clé inconnue ou manquante, de tout type non `str`, des SHA-256
  malformés, des `campaign_id` hors forme V2, des `created_at` invalides ou naïfs (y compris après reseal des
  hashes) ; Claim auto-cohérent divergent du plan refusé par `against_plan` ; canonicalisation identique à celle
  du Plan V2 et de la Slice B ; imports limités (AST), aucune E/S ni horloge ; aucun module historique ne
  référence E1 ; aucun fichier créé.
- **E2 (à spécifier en tests lors de son implémentation)** : refus avant création pour chaque source
  falsifiée, non persistée ou mal ancrée, preuves incomplètes, sentinelle, verrou résiduel, champs réservés
  non nuls ; deux puis huit **processus réels** synchronisés (exactement un gagnant) ; crash avant création,
  après création avant écriture, pendant l'écriture, avant et après `fsync` ; échecs simulés de `fsync`,
  d'espace disque, de permissions et de relecture ; Claim déjà présent (valide, vide, tronqué, corrompu) ;
  sentinelle, verrou ou Manifest modifiés entre les deux appels D5 ; aucune lecture de marché ni suppression
  de Claim (AST) ; `save_exclusive(durable=False)` inchangé ; suite complète verte.
- **Qualification manuelle du volume cible (non démontrable par tests)** : contention `O_EXCL` multiprocessus
  et comportement de `fsync` sur le vrai volume, avant toute exécution réelle. La survie à une panne
  d'alimentation réelle n'est pas démontrable par les tests.

## Décision 23 — Slice E3 : exécution contrôlée du `FINAL_HOLDOUT` (contrat normatif, 2026-10-12)

**Statut au 2026-10-12** (note factuelle additive ; les notes datées antérieures restent exactes pour leur date) :
- **E1 publié** : commit `707ec51b7edc52e5b5d8c4b040d9454f83b27e45`. **E2 publié** : commit
  `9c2bf7ef5ccf692e9d89db7b0ca61038bbd962e4` (HEAD = `origin/master` à la rédaction de cette Décision).
- Tests rapportés lors de la revue finale d'E2 : 3772 réussis, 2 ignorés. Ils n'ont pas été rejoués pour rédiger
  cette Décision, qui ne modifie aucun code.
- **E3 = conception documentée par la présente Décision, en cours de validation documentaire, NON IMPLÉMENTÉE.**
  Aucun module E3 n'existe. Tout artefact, fonction, champ ou fichier introduit ci-dessous est
  **SPÉCIFIÉ, NON IMPLÉMENTÉ**, sauf ceux que 23.1 désigne « existant ».
- **Le mode `REAL` est DÉSACTIVÉ et NON QUALIFIÉ.** Aucune qualification d'infrastructure (hôte Linux, volume, OCI,
  autorité de temps, fournisseur de données, ingesteur, coffre) n'a été réalisée, et aucune n'est affirmée.
- Aucun accès `FINAL_HOLDOUT` nouveau n'a eu lieu pour `AF-V-07` (l'accès antérieur et distinct d'AF-V-01 reste
  documenté dans `DOMAIN_MODEL.md` §12). Aucun Claim réel n'existe. `GATE V` NON PASSÉE. Aucun Champion qualifié.

**Portée** : cette Décision précise sans les contredire les Décisions 2, 9, 10, 11, 13, 16, 20, 21 et 22. Elle ne
modifie aucune formule d'identité ou de hash existante (`scope_key`, `preregistration_id`,
`campaign_protocol_fingerprint`, `campaign_id`, `claim_id`, `claim_content_hash`), ni les 14 clés du Claim (22.3), ni
l'API d'E2, ni la sémantique de V1, ni aucun artefact historique. Ses amendements aux décisions antérieures sont
inventoriés en 23.22 et sont strictement additifs. **Si une implémentation découvre qu'un contrat existant doit
changer, elle s'arrête et demande un amendement explicite de cette ADR ; elle ne contourne rien.**

### 23.1 — État de chaque composant (existant ou spécifié)

**Existant** (commit `9c2bf7e`) : `FinalHoldoutAccessClaim` et ses fonctions pures (E1) ;
`acquire_final_holdout_access_claim(campaign_dir, *, preregistration_path, research_run_path, split_plan_path,
policy_path, repo_dir=None, created_at=None)` et `load_final_holdout_access_claim(plan, campaign_dir)` (E2) ;
`atomic_json_store.save_exclusive(path, data, kind, *, durable=False)` et `ExclusiveCreationIncompleteError` ;
`assert_gate_v_pre_holdout_evidence_complete` (D5) ; `GateVCampaignManifestV2` (champs 13-17 réservés à `None`) ;
`dataset_split.HoldoutAccessEvent` (8 champs) avec `build_holdout_access_event`, `save_holdout_access_event`
(`save_atomic`, non exclusif), `load_holdout_access_event` (`load_tolerant`), `list_holdout_access_events` ;
`validation_oos.run_oos_validation` ; `engine.run_backtest(..., end_boundary=)` ;
`strategy_contracts.resolve_state_ready_boundary` ; `ResearchRun` (`engine_version`, `git_sha` optionnel) ;
`market_data.content_hash.content_hash` ; `job_store.build_local_csv_snapshot_id`.

**Spécifié, non implémenté** : tout le reste de cette Décision, dont `GateVProspectiveCommitment`,
`S0ProvenanceDeclaration`, `IngestionRecord`, `GateVHoldoutSnapshotAttachment`, `CommitmentVoidRecord`, le registre
et ses admissions, les déclarations, l'inventaire, l'attestation, l'autorisation, `ReadIntent`, `DataReceipt`,
`ClosingRecord`, le chargeur par octets (`engine.load_data_from_bytes`), l'écrivain exclusif de
`HoldoutAccessEvent`, le lister strict, l'identifiant OOS déterministe, le générateur synthétique et le wrapper
`run_gate_v_final_holdout_validation` (Décision 13).

### 23.2 — Modes `SYNTHETIC` et `REAL`

- `SYNTHETIC` est le mode par défaut et le seul utilisable pendant le développement. `REAL` est **désactivé** :
  une constante `REAL_FINAL_HOLDOUT_ENABLED = False` (spécifiée) ne passe à `True` que par un commit délibéré,
  postérieur au rapport de qualification de 23.21. Avec la constante à `False`, toute tentative `REAL` est refusée
  avant toute lecture.
- **Formats de snapshot disjoints** : `REAL` n'accepte que `local_csv:sha256:<64 hex>` ; `SYNTHETIC` n'accepte que
  `synthetic_csv:sha256:<64 hex>`. Chaque mode refuse le format de l'autre. `ig_demo:`, Parquet, EODHD et tout autre
  type sont **refusés dans les deux modes** tant qu'un amendement n'a pas fourni un contrat de vérification d'octets.
- **Anti-déguisement** : un snapshot `synthetic_csv:` est accompagné d'un manifeste de fixture (graine, nombre de
  lignes, pas, version du modèle de prix). Le chargeur régénère les octets avec le générateur déterministe et exige
  l'égalité du SHA-256. Une donnée réelle ne peut donc pas passer pour synthétique.
- `SYNTHETIC` exerce **le même chargeur, la même séquence et les mêmes écritures exclusives** que `REAL`. Il utilise
  un registre propre (`mode: SYNTHETIC`, `registry_id` distinct), un coffre synthétique distinct, une autorité de
  temps simulée **refusée en `REAL`** et des racines marquées synthétiques. Aucun artefact synthétique ne peut être
  pris pour un artefact `REAL`.
- **Profils de durabilité.** Le registre déclare un profil dans son identité. `REAL` exige `POSIX_DIR_FSYNC`
  (`fsync` du fichier puis du répertoire parent) et refuse tout autre profil. Sous Windows ou sur tout hôte sans
  `fsync` de répertoire, `SYNTHETIC` utilise `SIMULATED_DURABLE` : la même séquence s'exécute, la confirmation de
  durabilité est simulée et les fautes de `fsync` sont injectables par les tests. Un résultat `PublishedDurable`
  obtenu sous `SIMULATED_DURABLE` n'a aucune valeur de preuve de durabilité réelle.
- **Conditions cumulatives de `REAL`** : Linux ; UID effectif égal au compte de service (jamais root) ; worktree
  propre (aucun fichier suivi modifié) ; identité du code épinglée (23.4) ; rapport de qualification nominatif nommant le
  SHA du code qualifié, selon la chaîne de commits `X → R → B` de 23.21 ; autorisation d'acquisition valide (23.11) ; autorité du registre vérifiée (23.9) ; preuve de
  temps vérifiable (23.6) ; provenance suffisante (23.7). **Toute condition manquante, ambiguë ou non vérifiable
  refuse `REAL`.** Windows est réservé à `SYNTHETIC`.

### 23.3 — Fenêtre, exposition, classes, fraîcheur et indépendance scientifique

**Définitions.** `W = [ws, we)` est la fenêtre `FINAL_HOLDOUT` du `DatasetSplitPlan`, en ISO-8601 offset-aware,
comparée en instants UTC (borne naïve refusée). `S0` est le snapshot de recherche, égal à
`plan.dataset_snapshot_id` (donc à celui de la pré-enregistrement, du `ResearchRun`, du split et du Claim). `S_H` est
le snapshot du holdout (23.5). `E` est l'union des fenêtres de toute exécution ou lecture connue ou déclarée, pour tout
fournisseur et tout timeframe du même sous-jacent déclaré (`HoldoutAccessEvent`, `ValidationRun` OOS, jobs, campagnes V1
avec OOS, Claims, enregistrements `CONSUMPTION` du registre, `ReadIntent`, travaux non enregistrés déclarés). Les
`RESERVATION` et `ADMISSION` sans `CONSUMPTION` ne sont **pas** des expositions (aucune donnée n'a été lue) : elles
interviennent dans le test de recouvrement de 23.10, pas dans `E`. Un plan de split partageant la fenêtre ne compte
comme exposition que s'il a servi (événement, `ValidationRun`, job) ou s'il est porté par une `CONSUMPTION` d'une
autre campagne ; un plan jamais utilisé est inventorié mais n'est pas une exposition. *(Complété par 23.27.1 et
23.27.2 : exception des enregistrements attendus de la campagne courante à son étage.)*
`t_sel` est l'instant de la dernière décision de sélection ou de modification de stratégie informée par des données.
**Il est déclaré par l'humain** à l'engagement (23.4), puis éventuellement repoussé à une date plus tardive par
une déclaration ultérieure (23.11) : le `t_sel` effectif est le **maximum** entre celui de l'engagement et ceux des
déclarations, et une déclaration ne peut jamais le ramener à une date plus ancienne ; l'historique Git n'en fournit qu'une borne
inférieure indicative, établie par l'humain lors de la déclaration (par prudence, les corrections d'ingénierie
`2e133b3` et `7c1138e` du 2026-09-13 y sont examinées ; elles n'établissent pas à elles seules une sélection informée
par des données). F2 repose sur la déclaration. `t_anchor` est l'instant borne supérieure donné par une preuve de
temps forte (23.6). Le fait que `S0` ait un `period_end` ne définit pas `W`.

**Les trois classes de la Décision 22.2 sont inchangées** : `FRESH_UNEXPOSED_DECLARED`, `RETROSPECTIVE_EXPOSED`,
`UNDETERMINED`. `RETROSPECTIVE_EXPOSED` l'emporte sur `UNDETERMINED`. Toute source illisible, de schéma inconnu, de
fenêtre ou de fuseau inconnu donne `UNDETERMINED`. Le niveau de chronologie est une **preuve complémentaire, pas une
quatrième classe** : `PROSPECTIVE_ANCHORED` si les conditions F1 à F6 ci-dessous tiennent, `UNSEEN_HISTORICAL` si
aucune exposition n'est enregistrée mais que ces conditions ne tiennent pas, `NOT_APPLICABLE` sinon.

**Seule la classe `FRESH_UNEXPOSED_DECLARED` avec le niveau `PROSPECTIVE_ANCHORED` permet l'admission** (23.10).
`RETROSPECTIVE_EXPOSED`, `UNDETERMINED` et `FRESH_UNEXPOSED_DECLARED` avec `UNSEEN_HISTORICAL` sont refusés avant
toute admission. Conditions de `PROSPECTIVE_ANCHORED`, toutes obligatoires :
- **F1** `W ∩ E = ∅` en instants UTC, `E` complet et lisible, aucun élément `UNDETERMINED`.
- **F2** `ws ≥ max(fin de E, t_sel)` et `t_sel ≤ t_anchor`.
- **F3** `S0` ne contient aucune donnée de `W` : `max(time)` de `S0` calculé sur ses octets est strictement
  inférieur à `ws` (vérifié à la création de l'engagement et avant le Claim). La colonne `time`, naïve, est
  interprétée en UTC, contrat de `engine._add_market_time_columns` ; cette hypothèse est déclarée, non prouvée.
- **F4** la fenêtre `W` est réservée de façon durable dans le registre (`RESERVATION`, 23.10) avant l'ancrage, puis
  l'engagement est ancré par une preuve de temps forte vérifiable (23.6) avec `genTime + exactitude + marge ≤ ws`.
- **F5** `S_H` est ingéré après `we` (23.7) ; la plage d'ingestion est `(fin de S0, we)`.
- **F6** les déclarations humaines nominatives sont enregistrées et liées par hash (23.11). Aucun mécanisme de
  signature cryptographique n'est spécifié ; « nominatif » signifie déclaré sous un nom, sans authentification forte.

Un nouveau snapshot, un nouveau `scope_key`, un nouveau `split_plan_id`, un autre fournisseur ou un autre timeframe
**n'établit jamais la fraîcheur**.

**Indépendance scientifique — séparation obligatoire de cinq dimensions.** Aucune n'est transformée en une autre.
`FRESH_UNEXPOSED_DECLARED` reste une **classification déclarative**.

| Dimension | Ce qui l'établit | Ce qu'elle ne prouve pas |
|---|---|---|
| Provenance technique | hash, taille, enregistrement d'ingestion, écho du fournisseur | la fraîcheur, l'origine économique des prix |
| Fraîcheur chronologique | preuve de temps forte, `ws` postérieur à `E` et `t_sel` | l'absence de consultation humaine |
| Historique documenté des expositions | inventaire, admissions, événements | l'absence d'exposition non enregistrée (registre local, `results/` non versionné) |
| Déclarations humaines | attestation nominative, sans authentification forte | la véracité de la déclaration |
| Décision de qualification scientifique | Human Gate distinct (ADR 0024 Décision 15, Décision 12) | — (hors E3) |

Une preuve d'horodatage, une attestation nominative, une identité de snapshot ou un enregistrement d'admission **ne
prouvent pas l'absence absolue de contamination humaine** (connaissance de marché, consultation informelle,
travaux non enregistrés). E3 produit des preuves d'audit ; il ne certifie jamais l'indépendance et ne prononce aucun
verdict (23.25).

### 23.4 — `GateVProspectiveCommitment` (engagement prospectif, spécifié)

**Pourquoi.** `dataset_snapshot_id` est le SHA-256 des octets complets d'un fichier (`local_csv:sha256:<hash>`). Il
entre dans `scope_key`, `preregistration_id`, `campaign_protocol_fingerprint` et donc `campaign_id`, le Plan V2 et le
Claim. Si ce fichier contenait des barres de `W`, ses octets dépendraient de prix qui n'existent qu'à `we` et son
identifiant ne serait calculable qu'après `we` : **la chronologie `t_anchor < ws < we < acquisition` est impossible
pour un snapshot unique contenant le holdout**. Le modèle à deux snapshots (23.5) la rend réalisable sans toucher à
ces identités : la pré-enregistrement, le Plan V2 et le Claim lient `S0`, qui existe déjà ; `W` est un intervalle futur
déclaré dans le split (le constructeur de `DatasetSplitPlan` et `_derive_plan` ne contrôlent que l'égalité des
identifiants et la chronologie des zones, jamais la couverture des données ; `_derive_plan` exige en outre une zone
`validation` non nulle et calcule la géométrie des folds).

**Artefact.** Chemin `<campaign_dir>/prospective_commitment.json`, création exclusive durable, **un seul par campagne**.
Version `gate_v_prospective_commitment_v1`. Création **après** que D5 est complète (WF, MC, PS ; statut
`EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT`) et **avant** `ws`. **Séquence obligatoire** : engagement créé →
**réservation** durable de `W` dans le registre (`RESERVATION`, 23.10) → preuve de temps **portant sur l'enregistrement
de réservation** (23.6). Une réservation
refusée (recouvrement avec une autre réservation, admission ou exposition) rend l'engagement nul : une fenêtre
ne peut donc jamais être engagée par plusieurs campagnes concurrentes, ce qui interdit de n'admettre qu'après `we` la
variante la plus favorable parmi plusieurs engagements ancrés. Canonicalisation de la Décision 20.3.
`commitment_id = SHA256(canonical_json(champs sémantiques))` ; `commitment_content_hash = SHA256(canonical_json(
champs sémantiques + commitment_id + created_at))`. **Écart voulu avec E1** (où `created_at` est exclu des deux
hashes, inchangé) : ici le successeur épingle le `content_hash`, ce qui rend une modification a posteriori d'un
horodatage détectable. Ce n'est pas une preuve de date (23.6).

Champs sémantiques : `campaign_id`, `preregistration_id`, `preregistration_content_hash`,
`campaign_protocol_fingerprint` (projections du plan) ; `window_start`, `window_end` (égaux à
`plan.final_holdout`) ; `research_snapshot_id` (S0) ; hash de `S0ProvenanceDeclaration` ; `oos_parameters`
littéraux et `oos_parameter_selection_rule = "LITERAL_PREDECLARED"` ; configuration d'exécution
(`initial_capital`, `spread`, `slip_in`, `slip_out` explicites, `strategy_module`) et son hash ; identité du code
(SHA Git complet, arbre propre, hashs SHA-256 des fichiers du moteur, de la stratégie, de `validation_oos.py`, du
chargeur, de l'orchestrateur, de l'ingesteur et du registre ; la règle de vérification est l'égalité exacte du SHA Git
complet courant avec celui engagé, à chaque démarrage `REAL` ; `ENGINE_VERSION`, valeur calculée de `required_warmup(oos_parameters)`) ; références (id et
`validation_run_record_hash`) des `ValidationRun` WF/MC/PS : le Manifest V2 ne porte que leurs identifiants, et
`ValidationRun` n'a pas de `content_hash` ; `validation_run_record_hash` (spécifié) = SHA-256 du JSON canonique
(Décision 20.3) de l'enregistrement persisté ; hash de la configuration source du job qui a servi au Walk-Forward
(`config_used.json`, base de la comparaison des coûts, 23.16) ; règle d'acquisition de `S_H`
(fournisseur, symbole, convention de cotation, timeframe, fuseau d'origine, calendrier et sessions, règle de
couverture, adaptateur et sa version, nombre maximal de tentatives d'ingestion, plage `(fin de S0, we)`) ;
`registry_id` logique ; `t_sel` déclaré à l'engagement (une déclaration ultérieure ne peut que le repousser à une date plus tardive ; `t_sel`
effectif = maximum, 23.3 et 23.11).

**Immuabilité.** Aucun champ ne change après la création. Un changement de protocole, de paramètres, de coûts, de
code ou de règle d'acquisition invalide l'engagement. Un engagement non ancré ou invalide est annulé par un
`CommitmentVoidRecord` (23.8) et la campagne devient inutilisable pour E3 ; une nouvelle tentative exige une nouvelle
campagne (nouveau scope), donc un nouvel engagement ancré avant son propre `ws`, sur une fenêtre qui ne recoupe pas
celle de la campagne nulle si une réservation avait été publiée (elle n'est jamais libérée, 23.10). Rien de cet artefact n'entre dans
les identités historiques.

### 23.5 — Deux snapshots, `S0` et `S_H` ; audit de ce qui a réellement été consulté

- **`S0`** : snapshot de recherche. Le Plan V2, la pré-enregistration, le `ResearchRun` et le Claim continuent de le
  référencer, inchangés. Il est vérifié (hash, `max(time) < ws`) et analysé **avant** le Claim : c'est une donnée de
  recherche, pas du holdout.
- **`S_H`** : snapshot futur scellé, contenant les barres contiguës de `(fin de S0, we)`, donc le contexte entre
  `S0` et `ws` et la fenêtre `W` elle-même. Il est lié par l'attachment (23.8), jamais par le Claim. L'exécution
  `FINAL_HOLDOUT` consulte `S_H` après vérification de l'attachment et de son hash, avec `S0` comme contexte.
- **Amendement de la portée de 22.12.4** (sans modifier E1 ni E2) : « vérifier le contenu des données de marché
  contre `dataset_snapshot_id` » s'entend, pour une campagne prospective, comme (i) les octets de `S0` sont vérifiés
  contre `plan.dataset_snapshot_id` et (ii) les octets de `S_H` sont vérifiés, au moment de l'unique lecture,
  contre l'identifiant de `S_H` porté par l'attachment. **Le Claim n'atteste jamais `S_H`.**

**Liens d'audit exacts.** Chaque identité a un porteur nommé ; aucune n'est déduite d'une autre.

| Identité | Porteurs |
|---|---|
| Snapshot de recherche (`S0`) | Plan V2, pré-enregistration, Claim, `ReadIntent.research_snapshot_id`, `DataReceipt` |
| Snapshot réellement consulté (`S_H`) | `Attachment`, `ReadIntent.holdout_snapshot_id` (attendu), `DataReceipt.holdout_bytes_sha256` (observé), `ClosingRecord` ; `HoldoutAccessEvent` canonique via son champ `reason`, qui contient `read_intent_id` et l'identifiant de `S_H` (donc couvert par le hash de la Décision 13) ; `ValidationRun` OOS via le `ClosingRecord` (qui épingle son `validation_run_record_hash`) et via l'événement qui la référence |
| Fenêtre effectivement exécutée | `plan.final_holdout`, `ReadIntent`, spécification de la `ValidationRun` OOS (`holdout_start`, `holdout_end`), `ClosingRecord` ; l'événement canonique ne la porte qu'indirectement (`split_plan_id`, et `read_intent_id` dans `reason`) |
| Hash et taille des octets de `S_H` | `IngestionRecord` (ingestion), `DataReceipt` (unique lecture) |
| Entrée transmise au moteur | `DataReceipt.engine_input` : preuve de construction + empreinte (ci-dessous) |
| Version et paramètres du moteur | `ReadIntent` et `ClosingRecord` : `ENGINE_VERSION`, SHA Git, hashs de fichiers, `end_boundary`, coûts, module de stratégie, `oos_parameters`, `required_warmup` |

`DataReceipt.engine_input` contient : `s0_sha256`, `holdout_bytes_sha256`, identifiant, version et hash de code du
chargeur, colonnes et dtypes, `n_rows_s0`, `n_rows_s_h`, dernière heure de `S0` et première heure de `S_H`,
`n_rows_transmitted`, première et dernière heure UTC transmises, borne de troncature `end` (exclusive) et
`engine_input_digest` = SHA-256 d'une sérialisation canonique ligne à ligne des lignes effectivement transmises à
`run_oos_validation` (sérialisation fixée par la slice du chargeur, avec vecteurs littéraux calculés hors du code
testé). La preuve de construction (hashs d'entrée, version et code du chargeur, règle de troncature) et l'empreinte
sont toutes deux obligatoires.

**Règle d'attribution.** La `ValidationRun` OOS conserve le schéma existant ; son `dataset_snapshot_id` vaut
`plan.dataset_snapshot_id`, c'est-à-dire `S0`. **Aucun consommateur ne doit lire ce champ comme le snapshot consulté
d'une campagne prospective** : le snapshot consulté est celui du `ClosingRecord` et du `DataReceipt`. Un résultat
n'est jamais attribué à `S0` seul. Il en va de même du champ `dataset_snapshot_id` de l'événement canonique, fixé à
`S0` (23.13). `validation_run.py` n'est pas modifié.

### 23.6 — Preuves chronologiques recevables et conditions de refus

| Niveau | Preuve | Statut |
|---|---|---|
| Fort | jeton RFC 3161 sur l'empreinte `reservation_content_hash` (les 32 octets du SHA-256, hex décodé ; l'enregistrement de réservation épingle `commitment_content_hash`) avec chaîne de certificats stockée ; ou preuve OpenTimestamps **confirmée** dans un bloc | obligatoire en `REAL` |
| Corroboration | enregistrement d'hébergeur Git (événement de push, release) figé et haché | jamais suffisant seul : modifiable par le propriétaire |
| Non recevable | hash Git, date de commit, `created_at`, `attested_at`, mtime, horloge système | jamais une preuve de date |

- Une preuve de temps prouve que l'empreinte **existait** avant sa borne ; elle ne prouve ni la date de création, ni
  l'absence de consultation.
- RFC 3161 : le jeton est vérifié contre une liste d'autorités de confiance (chaînes et politiques) **committée dans le
  dépôt** ; la validité du certificat est contrôlée à `genTime` ; la révocation n'est vérifiable qu'en ligne et son
  absence de vérification donne `REVOCATION_UNKNOWN`. La borne est `genTime + exactitude`. Un `nonce` évite le rejeu.
- OpenTimestamps : seule une attestation de bloc confirmée compte ; une attestation en attente est insuffisante.
- Condition : `borne + marge ≤ ws`. La marge est une décision opérationnelle ouverte (23.24). *(Précisé par 23.27 et
  23.28 : une marge absente ou ≤ 0 n'est jamais vérifiée, F4 `UNVERIFIED` — ou `NOT_MET` si la borne seule dépasse `ws`.)*
- **Fail-closed** : outil de vérification indisponible, chaîne absente, autorité hors liste, empreinte différente,
  `genTime` illisible ou postérieur, ou preuve en attente : état `TIME_PROOF_UNVERIFIABLE`, l'engagement n'est pas
  ancré, aucune campagne prospective n'existe, `REAL` est refusé. Aucune autorité de temps ni outil de vérification
  n'est choisi ou qualifié par cette Décision.
- La vérification a lieu deux fois : à l'ancrage (en ligne, avec révocation) et au démarrage d'E3 (hors ligne, contre
  la chaîne figée).
- **Ce qui est horodaté** : l'enregistrement `RESERVATION` (23.10), jamais l'engagement seul. Comme la réservation
  épingle `commitment_content_hash` et occupe un slot de la chaîne du registre, la preuve établit à la fois l'existence
  de l'engagement, l'antériorité de la réservation et son rang. Un jeton obtenu sur l'engagement seul n'établit
  aucune réservation antérieure à `ws` et n'est pas recevable : deux engagements ancrés « à la main » avant `ws`, dont
  la réservation n'aurait lieu qu'après `we`, ne peuvent donc pas être départagés a posteriori.
- **Artefact `ReservationTimeProof`** (spécifié) : `<campaign_dir>/reservation_time_proof.json`, création exclusive
  durable, un seul par engagement, écrit **seulement** pour une preuve vérifiée (un échec de vérification n'écrit
  aucun artefact et laisse l'engagement non ancré). Champs : version de schéma, type de preuve (`RFC3161` ou
  `OPENTIMESTAMPS`), `reservation_content_hash` visé et `commitment_content_hash` correspondant, octets de la preuve
  (ou référence et SHA-256) avec la chaîne ou les en-têtes nécessaires, identité et version de l'outil de
  vérification, empreinte de la liste de confiance utilisée (elle doit égaler celle du dépôt au SHA épinglé par
  l'engagement), borne de temps UTC retenue (`genTime + exactitude`), résultat de la vérification, `created_at`. Son
  `content_hash` est épinglé par l'admission et le `ReadIntent` (23.10, 23.13). L'`ADMISSION` vérifie que la preuve
  vise **sa propre** réservation et que `borne + marge ≤ ws`.
- **Témoin de tête du registre** (spécifié) : après chaque enregistrement (`RESERVATION`, `ADMISSION`, `CONSUMPTION`,
  `REBIND`, calendrier précisé en 23.10 étape 6 bis), le couple (`seq`, `content_hash`) de la tête de la chaîne est
  couvert par une preuve de temps de même niveau et copié sur un support
  indépendant de l'hôte (support : décision opérationnelle, 23.24). Il sert uniquement à détecter un retour en
  arrière du registre (23.9).

### 23.7 — Ingestion technique cloisonnée et provenance

**Quatre classes d'accès aux octets de `S_H`.**

| Classe | Qui | Quand | Permis | Interdit |
|---|---|---|---|---|
| A. Ingestion et stockage | ingesteur dédié | après `we` | copier en flux vers le coffre scellé | analyser, afficher, échantillonner, journaliser le contenu |
| B. Identité et intégrité | le même ingesteur, puis E3 à l'unique lecture | ingestion, puis à l'unique lecture après le `ReadIntent` | SHA-256 en flux et taille | toute autre statistique |
| C. Recherche ou personne | personne | jamais avant le Claim | rien | tout affichage, backtest, sélection de paramètres |
| D. Moteur de validation | E3 seul | après Claim et `ReadIntent` | une lecture unique | toute relecture |

**Exemption d'ingestion, bornée.** L'ingesteur traite les octets en flux pour le transport, le SHA-256 et la taille.
Il ne produit qu'un `IngestionRecord` : taille, SHA-256, plage demandée, `acquired_at`, écho du fournisseur
(transport et métadonnées de réponse), identité de l'ingesteur (SHA Git, hash de fichier), hôte. Interdits :
parsing, affichage, échantillonnage, statistique, journalisation du contenu, copie hors coffre, transmission à un
autre processus. Le module de l'ingesteur n'importe aucune bibliothèque d'analyse (test AST).

**Portée exacte des garanties** : le hash et la taille sont des fonctions déterministes de tout le contenu. La taille
indique grossièrement le nombre de barres ; le hash permet de confirmer une hypothèse sur un fichier connu. Le
cloisonnement garantit l'absence de **valeurs, statistiques et information par barre** avant le Claim. **Il ne
garantit pas une absence absolue d'information dérivée du contenu.**

**Cloisonnement requis (à démontrer sur la machine cible, non démontré aujourd'hui)** : coffre lisible par un seul
compte de service ; source non interactive (script ou API) ; un export manuel depuis une interface graphique est
exclu car il affiche les prix ; fournisseur, instrument et timeframe identiques à ceux déclarés pour `S0`. Tant que
cette démonstration manque, `REAL` reste non qualifié.

**Provenance de `S_H`.**

| Champ | Statut | Où et comment | Si absent ou insuffisant |
|---|---|---|---|
| Fournisseur réel | déclaré (engagement) + constaté localement par l'ingesteur (hôte, certificat TLS, entêtes de réponse capturés ; l'`IngestionRecord` est auto-produit, non signé, sans preuve de temps) | ingesteur | `REAL` refusé |
| Instrument exact (symbole fournisseur) | déclaré + écho de la réponse du fournisseur ; impossible à prouver depuis les octets | ingesteur | `REAL` refusé si l'adaptateur ne fournit pas d'écho |
| Convention de cotation | déclaré, égale à celle de `S0` | déclaration humaine | refus si absente ; inscrit dans `provenance_residuals` |
| Timeframe | déclaré + écho + calculé après Claim (écarts d'horodatage multiples du pas) | ingesteur, E3 | `REAL` refusé |
| Fuseau d'origine, conversion UTC | déclaré, non prouvable ; cohérence avec `S0` contrôlée après Claim | déclaration, E3 | refus si absent |
| Calendrier et sessions | déclaré | engagement | refus si absent |
| Plage demandée | calculé (paramètres de requête) | ingesteur | refus |
| Plage réellement couverte | calculé après Claim (première et dernière barre) contre la règle de couverture engagée | E3 | `EXECUTION_VOID` |
| Continuité avec `S0` | calculé après Claim (première barre de `S_H` strictement postérieure à la dernière de `S0`, colonnes et en-tête égaux) | E3 | `EXECUTION_VOID` |
| Hash, taille, heure d'acquisition | calculé à l'ingestion, hash recalculé à l'unique lecture | ingesteur, E3 | refus |
| Version et identité de l'ingesteur | calculé (SHA Git, hash de fichier) | ingesteur | refus |
| Identité économique réelle de l'instrument, intégrité des prix du courtier | impossible à prouver | — | résiduel accepté par l'humain |

**Règle de suffisance.** Les champs de niveau 1 (fournisseur, symbole, timeframe, plage demandée, hash, ingesteur)
doivent être vérifiés ou constatés localement par l'ingesteur (jamais attestés par le fournisseur : aucune signature
n'est spécifiée). Les champs de niveau 2 (convention, fuseau, calendrier)
peuvent rester déclarés mais doivent être explicitement égaux à ceux de `S0` ; leur caractère non prouvé est inscrit
dans `ClosingRecord.provenance_residuals`. Le niveau 3 est impossible à prouver. **Aucun fournisseur n'a été vérifié ;
la capacité d'écho des API reste à établir par fournisseur.** Sans adaptateur fournissant l'écho de niveau 1, `REAL`
est refusé.

**`S0ProvenanceDeclaration`** (spécifié, additif). Les artefacts de `S0` n'établissent que des noms de fichier : son
`data_manifest.json` porte `provider: "local_csv"`, `instrument: "nasdaq_3m"` et `timezone: "UTC"` déclaré. Une
déclaration nominative, liée à l'identifiant de `S0`, énonce le fournisseur, le symbole, la convention de cotation et le
fuseau réels. Aucune identité historique de `S0` n'est modifiée.

### 23.8 — Attachment `S_H` : unicité et absence de sélection opportuniste

- **Une seule ingestion complète par engagement.** Le coffre contient un répertoire `<coffre>/<commitment_id>/` avec
  `s_h.csv`, `ingestion_record.json`, et `attempt_<n>.json` (`gate_v_ingestion_attempt_v1`) pour les tentatives échouées (classe d'erreur, nombre
  d'octets et SHA-256 des octets reçus, jamais de contenu : l'absence de sélection entre tentatives reste auditable). La création est exclusive : une seconde ingestion complète est impossible. La première
  ingestion déclarée complète lie l'engagement. « Complète » est défini par le contrat de l'adaptateur (fin de plage
  rapportée par le fournisseur et `IngestionRecord.complete = true`) ; un adaptateur dont le contrat ne définit pas
  cette notion est refusé. Le nombre maximal de tentatives est celui de l'engagement ; l'échéance d'ingestion après
  `we` est une décision opérationnelle (23.24). Les tentatives échouées sont journalisées et comptées (23.11).
- **Un seul attachment immuable par engagement**, `<campaign_dir>/holdout_snapshot_attachment.json`, création
  exclusive durable, **dérivé** de l'`IngestionRecord`, jamais choisi. Il lie : `commitment_id` et
  `commitment_content_hash`, `S0`, `S_H`, `content_hash` de l'`IngestionRecord`, plage et fenêtre égales à celles
  engagées. Toute inégalité l'invalide. Il n'entre dans l'identité d'aucun artefact antérieur.
  `attachment_id = SHA256(canonical_json({attachment_semantics_version, commitment_id, research_snapshot_id,
  holdout_snapshot_id, ingestion_record_content_hash}))` ; `attachment_content_hash` = hash du contenu complet,
  `created_at` inclus.
- Le coffre ne doit contenir que les fichiers attendus ; un fichier supplémentaire fait refuser `REAL`.

| Cas | Traitement |
|---|---|
| Plusieurs ingestions du même intervalle | la seconde est refusée |
| Deux fichiers `S_H` de hashs différents | impossible via l'ingesteur ; si copiés à la main, seul le fichier désigné par l'attachment est lu et son hash vérifié |
| Snapshot partiel | la règle de couverture engagée avant la fenêtre est contrôlée après le Claim ; sinon `EXECUTION_VOID` |
| Erreur d'ingestion permanente | engagement nul, jamais remplacé |
| Nouvelle tentative de rattachement | refusée |
| Attachment créé, non utilisé | reste ; aucun effet ; la fenêtre n'est pas consommée |
| Changement de fournisseur ou de timeframe, ou de période | non conforme à l'engagement : nul |

**Engagement nul.** `CommitmentVoidRecord` (spécifié) : enregistrement exclusif, nominatif, avec une classe de cause
(`INGESTION_FAILED_PERMANENT`, `PROVENANCE_MISMATCH`, `SNAPSHOT_INTEGRITY`, `PROTOCOL_ERROR`,
`TIME_PROOF_UNVERIFIABLE`, `RESERVATION_REFUSED`). Une annulation survenue avant toute réservation ne protège aucune
fenêtre : seule une `RESERVATION` publiée protège. `RESERVATION_STALE` est enregistrée avec la cause
`RESERVATION_REFUSED` (la protection de la fenêtre se lit dans la chaîne du registre, pas dans la cause : une
réservation publiée protège, même devenue `RESERVATION_STALE`). La `RESERVATION` de la
campagne nulle n'est **jamais libérée** (23.10) : la fenêtre est perdue pour `GATE V`, que l'annulation ait lieu avant
ou après `ws`. Une nouvelle campagne doit, si une réservation avait été publiée, viser une fenêtre qui ne recoupe pas la sienne, et
être ancrée avant son propre `ws`. Un `CommitmentVoidRecord` est refusé dès qu'une `CONSUMPTION` ou un `ReadIntent` existe ; `EXECUTION_VOID_<cause>` et
`CLOSED_COMPLETE` sont des états finaux. **Une erreur de snapshot ne donne donc jamais le droit de choisir un fichier de remplacement.** Deux
campagnes rivales sur la même fenêtre : la première **réservation** gagne (23.10) ; la seconde ne peut pas être
ancrée. Une réservation sans `ClosingRecord` terminal est comptée comme tentative abandonnée dans la comptabilité des
essais (23.11) : un abandon sélectif reste visible.

### 23.9 — Registre transversal mono-hôte Linux : autorité physique et limites

**Garantie réelle, restreinte** : le registre est autoritaire **uniquement pour un déploiement contrôlé sur un hôte
Linux et un volume local qualifié**. `registry_id`, `instance_id`, permissions et hashs **ne sont jamais une preuve
universelle d'unicité entre machines**. Deux hôtes indépendants avec chacun leur dépôt et leur registre ne sont pas
détectables par ce mécanisme.

- **Constat** : `campaign_root` est toujours fourni par l'appelant (`results/job_xxx/gate_v/...`, Décision 16) ;
  `results/` est gitignoré, donc chaque worktree et chaque job a son propre espace. Un registre par job ou par
  worktree ne peut pas empêcher deux admissions incompatibles : un registre global unique est donc requis.
- **Chemin et configuration.** Un chemin canonique fixe, hors dépôt, hors worktrees, hors `results/`, déclaré
  uniquement dans un fichier de configuration appartenant à root, non modifiable par les comptes de recherche
  (permissions exactes : décision opérationnelle, 23.24). En `REAL`, aucun paramètre,
  aucune variable d'environnement et aucun champ de campagne ne redéfinit ce chemin. Le même fichier déclare le chemin
  du coffre, le compte de service et la liste des hôtes autorisés (identifiants machine).
- **Protection par le système** : répertoire propriété du compte de service, écriture réservée à ce compte, fichiers
  en lecture seule après création (permissions exactes : décision opérationnelle, 23.24) ; `REAL` refuse si l'UID effectif n'est pas celui du service ou est root. Un attribut `append-only` sur le
  répertoire des admissions est une option à qualifier, non supposée.
- **Identité logique et physique.** Logique : `registry_id`, committé dans le dépôt. Physique : `instance_id`
  aléatoire créé à l'initialisation, plus une liaison (UUID du volume, type de système de fichiers, inode du répertoire,
  identifiant machine) écrite dans la configuration de root, **hors** du registre. Une copie du répertoire reproduit
  `registry_id` et `instance_id` mais change l'inode ou le volume.
- **Vérifications** à chaque démarrage `REAL`, avant l'admission et avant le `ReadIntent` : propriétaire et mode de la
  configuration ; chemin réel égal au chemin configuré, sans lien symbolique ; système de fichiers dans une liste
  fermée de systèmes locaux à qualifier (réseau, overlay, FUSE, tmpfs refusés) ; UUID, inode et identifiant machine égaux
  à la liaison ; `identity.json` conforme (`registry_id`, `instance_id`, mode `REAL`, profil de durabilité `POSIX_DIR_FSYNC`) ; intégrité de la chaîne ; tête de
  chaîne au moins égale au dernier témoin de tête (23.6) ; hôte autorisé. Une restauration de l'ensemble de la
  machine ou du volume (instantané de machine virtuelle) conserve UUID, inode et identifiant machine : seul le témoin
  de tête, copié hors de l'hôte, permet de la détecter.
- **Copies, sauvegardes, restaurations, montages.** Une sauvegarde est une copie en lecture seule hors du chemin
  canonique et échoue à la liaison. Une restauration est une cérémonie humaine : nouveau répertoire, nouvel
  `instance_id`, liaison mise à jour par root, enregistrement `REBIND` dans la chaîne (anciennes et nouvelles
  liaisons, tête restaurée, justification). La tête restaurée doit être au moins égale à la plus haute tête
  référencée par un artefact connu et par le dernier témoin de tête (23.6), sinon refus. Un montage lié du même volume (même UUID
  et même inode) désigne le même registre.
- **Un seul domaine d'admission par déploiement** : la configuration déclare exactement un registre ; configuration
  absente, ambiguë ou hôte non listé donne un refus.
- **`REAL` est refusé** si l'autorité est ambiguë, absente, inaccessible, divergente, corrompue, incomplète ou non
  qualifiée. Il n'existe aucun repli sur un registre local.
- **Conservation** : append-only ; copie après chaque enregistrement sur un support indépendant ; aucune
  restauration par dessus un registre existant.
- **Limites explicites** : plusieurs hôtes indépendants ; un administrateur root qui falsifie configuration et
  registre ; E2 appelée hors E3 ; lecture manuelle des données ; `run_oos_validation` (publique) ; matériel qui ment
  sur `fsync` ; multi-machine et OCI non qualifiés ; tout enregistrement postérieur au dernier témoin de tête et non
  référencé par un artefact connu, qu'une restauration complète de la machine ferait disparaître ; un code antérieur à
  la Décision 23 (autre worktree ou branche), qui ignore silencieusement les événements étendus (23.13).

### 23.10 — Admission atomique, publication durable et concurrence

**Enregistrements du registre** (spécifiés) : un fichier `admissions/admission_<seq>.json` par enregistrement (le
répertoire et le motif de nom, hérités de l'ordre de conception, désignent **tous** les types), append-only, chaînés,
de quatre types.
- **`RESERVATION`** (avant `ws`, 23.4) : réserve `W` pour une campagne. Liée à `commitment_id` et
  `commitment_content_hash`. Refusée si `W` recoupe une autre réservation ou admission, ou si le lister strict des
  sources des racines d'audit (le même que celui de l'inventaire, sans attestation) renvoie une source pertinente.
  Elle n'ouvre aucun droit d'accès.
- **`ADMISSION`** (après `we`, 23.17) : convertit la réservation de la même campagne en droit d'enchaîner jusqu'au
  Claim. Liée à la réservation (`reservation_content_hash` ; `reservation_seq` est informatif), à `attachment_id` et
  `attachment_content_hash`, au `content_hash` de la `ReservationTimeProof`, aux hashs d'attestation et d'autorisation.
- **`CONSUMPTION`** (après le retour durable d'E2, avant le `ReadIntent`) : marque que le droit de la campagne est
  consommé. Liée à `claim_id`, `claim_content_hash` et à l'admission. C'est le **verrou d'exclusivité par
  `campaign_id` dans le registre** : il ne dépend pas du chemin du dossier de campagne.
- **`REBIND`** (23.9) : cérémonie de restauration.

**Unicité par campagne.** La chaîne contient au plus un enregistrement de chaque type `RESERVATION`, `ADMISSION` et
`CONSUMPTION` par `campaign_id`. Cette unicité est vérifiée à l'étape 2 de la publication, sous la même
sérialisation que le recouvrement. **Un second enregistrement du même type et de la même campagne n'est jamais
publié, même à contenu identique** : le chemin de publication le refuse (`CAMPAIGN_ALREADY_REGISTERED`, ou
`CAMPAIGN_ALREADY_CONSUMED` pour une `CONSUMPTION`). Pour `RESERVATION` et `ADMISSION` seulement, l'orchestrateur peut
**relire** l'enregistrement existant de sa campagne et le réutiliser sans rien publier si son contenu sémantique est
identique (reprise après crash, ci-dessous) ; cette réutilisation est une lecture, jamais une publication. **Pour une
`CONSUMPTION`, il n'existe aucune réutilisation ni idempotence** : elle est refusée dans tous les cas où une
`CONSUMPTION` de ce `campaign_id` existe, et la re-confirmation de durabilité n'est permise qu'à l'intérieur de l'appel
qui l'a publiée (il en connaît le slot). Une copie ou une restauration du dossier de campagne sous une autre racine
conserve son `campaign_id` : elle ne peut ni réserver une seconde fois, ni réutiliser une admission déjà suivie d'une
`CONSUMPTION`, ni atteindre le `ReadIntent` sans sa propre `CONSUMPTION`, que le registre n'accorde qu'une fois.

**Champs communs** à tous les types : `admission_semantics_version`, `registry_id`, `instance_id` (celui en vigueur,
voir `REBIND`), `seq`, `prev_content_hash` (slot 0 : SHA-256 de la chaîne UTF-8
`"gate_v_registry_genesis:" + instance_id`), type, `created_at`.
**Champs des types de campagne** (`RESERVATION`, `ADMISSION`, `CONSUMPTION`) : `campaign_id`, fenêtre, `commitment_id`,
`commitment_content_hash`, hash d'identité du code, `campaign_dir_locator` (indication de localisation, **hors
identité** : un déplacement du dossier n'invalide rien, Décision 16). `RESERVATION` ajoute `static_sources_digest`
calculé à la réservation par le lister strict. `ADMISSION` ajoute `static_sources_digest`, le hash de la projection de
recouvrement et les liens ci-dessus. `CONSUMPTION` ajoute `claim_id`, `claim_content_hash` et `admission_content_hash`.
**`REBIND`** n'a ni `campaign_id` ni fenêtre : `old_binding_hash`, `new_binding_hash`, tête restaurée (`seq`,
`content_hash`), justification, nouvel `instance_id`. Règle de chaîne : l'`instance_id` de chaque enregistrement est
celui du slot 0 jusqu'au premier `REBIND`, puis celui du dernier `REBIND` ; l'`instance_id` du `REBIND` lui-même est le
**nouveau** ; la continuité repose sur `prev_content_hash`, pas sur la valeur de genèse. `record_content_hash` (pour
une `RESERVATION`, `reservation_content_hash`) = SHA-256 du JSON canonique de l'enregistrement complet, `seq`,
`prev_content_hash` et `created_at` inclus : c'est lui que la preuve de temps horodate et que les successeurs épinglent. `admission_id` = hash sémantique (sans `seq`, `prev_content_hash`,
`campaign_dir_locator`, `reservation_seq` ni `created_at`) ; `admission_content_hash` = hash du contenu complet.
**Aucune libération ni suppression en V1** : une réservation ou une admission protège la fenêtre définitivement,
même sans Claim.

**Définitions.** *Ensemble pertinent* : les sources de l'inventaire dont la fenêtre recoupe `W` ou est inconnue, plus
les réservations et admissions d'autres campagnes qui recoupent `W`. Pour une campagne `FRESH_UNEXPOSED_DECLARED`,
cet ensemble est vide. `static_sources_digest` = SHA-256 de la liste canonique triée de l'ensemble pertinent
(identifiant canonique et `content_hash` de chaque élément) : c'est donc une constante tant qu'aucune exposition ni
aucun rival n'apparaît, et un ajout sans rapport avec `W` ne la modifie pas. `projection de recouvrement` = hash de la
liste des réservations et admissions d'autres campagnes qui recoupent `W` (ou illisibles). *(La phrase « Pour une
campagne `FRESH_UNEXPOSED_DECLARED`, cet ensemble est vide » est remplacée par 23.27.1.)*

**Granularité globale.** Aucun artefact ne porte d'instrument vérifié (le plan, la pré-enregistration, le
`ResearchRun` et le Claim n'ont pas de champ instrument ; seul `dataset_snapshot_id` existe). L'exclusivité porte donc
sur les fenêtres de l'ensemble du registre, sans clé d'instrument ni de timeframe ; l'instrument déclaré est noté pour
audit. Test de recouvrement : `a.start < b.end ∧ b.start < a.end` en instants UTC, contre toute réservation ou
admission d'un autre `campaign_id` ; une fenêtre illisible bloque tout.

**Publication** (tout type d'enregistrement). Succès atomique ≠ succès durable.
1. Lire la chaîne entière, vérifier hashs et numérotation dense ; barrière de lecture : `fsync` du répertoire.
2. Vérifier, selon le type :
   - types de campagne (`RESERVATION`, `ADMISSION`, `CONSUMPTION`) : unicité par campagne (ci-dessus) ; absence de
     recouvrement avec les enregistrements d'autres campagnes ;
   - `RESERVATION` : engagement valide ; `static_sources_digest` recalculé et ensemble pertinent vide ; aucune
     attestation à ce stade ;
   - `ADMISSION` : une `RESERVATION` de la **même** campagne, du même `commitment_content_hash` et de la même
     fenêtre existe, est durable, et aucune `ADMISSION` de cette campagne n'existe (une admission sémantiquement identique
     est réutilisée par relecture sans publication ; une admission différente donne un refus) ; la `ReservationTimeProof` vise
     cette réservation avec `borne + marge ≤ ws` ; préfixe de chaîne épinglé présent ; projection de recouvrement et
     `static_sources_digest` identiques à ceux de l'attestation ; attestation valide (classification recalculée
     égale), autorisation valide, déclarations inchangées. *(Complété par 23.27.4 : sept contrôles préalables,
     dont `inventory_id` et `inventory_content_digest`, répétés après tout conflit de slot.)* ;
   - `CONSUMPTION` : une `ADMISSION` durable de la même campagne existe ; aucune `CONSUMPTION` de ce `campaign_id`
     n'existe ; `claim_content_hash` égal à celui du Claim relu par E2.
   - `REBIND` : cérémonie humaine (23.9) ; le test de recouvrement ne s'applique pas (pas de fenêtre) ; la tête
     restaurée est vérifiée contre les témoins de tête.
3. Construire l'enregistrement du slot `n+1`.
4. Écrire un temporaire complet dans le **même répertoire** que les slots, avec un nom unique par tentative ;
   `fsync` du fichier.
5. `os.link(tmp, slot_n+1)`. `FileExistsError` signifie qu'un enregistrement concurrent a occupé le slot : jamais une
   raison de continuer silencieusement. On revient à l'étape 1 ; si les vérifications de l'étape 2 passent encore
   (la projection de recouvrement n'a pas changé), la tentative suivante vise le nouveau slot ; sinon, pour une
   `ADMISSION`, l'attestation est périmée (arrêt, nouvelle attestation et nouvelle autorisation humaines) et, pour une
   `RESERVATION`, l'engagement est nul. Le nombre de tentatives par appel est borné (valeur : décision opérationnelle,
   23.24) ; au-delà : arrêt `REGISTRY_CONTENTION`, rien n'est publié. *(Complété par 23.27.4 : pour une `ADMISSION`,
les sept contrôles préalables sont répétés après tout conflit de slot et doivent être inchangés pour toute nouvelle
tentative.)*
6. `fsync` du répertoire. Seul son succès donne `PublishedDurable`.
6 bis. **Témoin de tête** (`REAL`) : après chaque `RESERVATION`, `ADMISSION`, `CONSUMPTION` et `REBIND`, la tête
   publiée est couverte par une preuve de temps (23.6) et copiée hors de l'hôte. Pour une `RESERVATION`, la
   `ReservationTimeProof` fournit la preuve de temps ; la copie hors de l'hôte reste requise. Pour une `ADMISSION`, le témoin doit exister avant l'appel d'E2 ; pour une
   `CONSUMPTION`, avant le `ReadIntent` ; pour un `REBIND`, avant toute réutilisation du registre. Un échec de la
   preuve ou de la copie arrête la progression ; l'enregistrement reste, et le témoin peut être rejoué, jamais la
   publication.
7. Supprimer le temporaire, nommé `.registry.tmp.<uuid>` (un échec laisse un orphelin inoffensif, ignoré par le
   motif `admission_*.json`).
8. Pour une `RESERVATION` ou une `ADMISSION`, revérifier `static_sources_digest` ; s'il a changé (une exposition ou
   un rival est apparu), l'enregistrement reste et la campagne s'arrête : `RESERVATION_STALE` avant la preuve de temps
   (engagement nul), `ADMITTED_STALE` pour une admission (état **terminal pour E3**, sans transition sortante ; seule
   une décision humaine peut la déclarer nulle). Un changement détecté à l'étape 13 de 23.17, après le Claim, donne
   `EXECUTION_VOID_EXPOSURE_CHANGED` (terminal, sans lecture). Un changement de l'ensemble pertinent est une
   information d'exposition nouvelle. *(La comptabilité des essais n'est jamais comparée à cette étape, 23.27.3.)*

**E3 ne crée jamais le Claim si l'admission n'est pas `PublishedDurable`** selon le contrat du volume cible. Sous
Windows, le `fsync` d'un répertoire n'est pas disponible : la durabilité du lien n'est pas démontrable et `REAL` y est
refusé. Un slot visible mais non confirmé durable reste binding pour les autres écrivains (conservateur). Une
re-confirmation (nouveau `fsync` du répertoire) est permise, sauf pour une `CONSUMPTION` hors de l'appel qui l'a
publiée ; une re-publication ou une suppression ne l'est pas.

**Matrice de crash de la publication** (tout type ; échec fermé, aucune reprise destructive) :

| Crash ou échec | État disque | Effet | Reprise |
|---|---|---|---|
| Barrière de lecture (`fsync` du répertoire) en échec | rien de publié | refus | rejeu |
| Avant le temporaire, temporaire partiel ou complet avant `link` | orphelin `.registry.tmp.<uuid>` éventuel | aucun slot | rejeu avec un nouveau nom |
| `link` fait, avant `fsync` du répertoire | slot visible, peut disparaître après coupure | `PublishedUnconfirmed` : étape suivante interdite ; les autres écrivains le traitent comme binding | re-confirmation ; si le slot a disparu, rien n'a été publié (le rejeu reste soumis à l'unicité) ; **sauf `CONSUMPTION`** : après un redémarrage, décision humaine seulement (aucune re-confirmation hors de l'appel qui l'a publiée) |
| `fsync` du répertoire en échec (`EIO`) | slot possiblement présent | idem | re-confirmation (sauf `CONSUMPTION` : décision humaine), sinon décision humaine |
| `fsync` réussi, avant la suppression du temporaire | slot durable + orphelin | enregistrement confirmé | rien (orphelin ignoré) |
| Échec du témoin de tête (preuve ou copie) | slot durable, pas de témoin | progression arrêtée | rejeu du témoin seul (pour une `CONSUMPTION`, après redémarrage : décision humaine) |
| Étape 8 : `static_sources_digest` changé | enregistrement durable | `RESERVATION_STALE` (engagement nul) ou `ADMITTED_STALE`, terminal | décision humaine |
| `CONSUMPTION` durable, pas de `ReadIntent` | `CONSUMPTION` | droit consommé, lecture non déduite ; terminal (Décision 11) | aucune lecture, aucun second Claim |
| Slot illisible ou trou de numérotation | chaîne rompue | arrêt de tout `REAL` | décision humaine |

**Instant de péremption de l'inventaire.** Il devient périmé au premier de ces événements : une source non registre
change ; une réservation ou une admission d'une autre campagne dont la fenêtre recoupe (ou est illisible) apparaît ;
le préfixe épinglé n'est plus un préfixe de la chaîne ; la tête des déclarations change ; la version de la
classification change. Une réservation ou une admission **sans recouvrement** qui avance la tête ne périme **pas**
l'attestation. *(Dernière phrase remplacée par 23.27.4 : la comptabilité et les expositions étrangères, dont une
`CONSUMPTION` non recoupante, périment l'attestation.)*

**Argument de sérialisation.** `os.link` réussit pour exactement un appelant par slot. Invariant : si le slot `k`
existe, les slots `0..k-1` existent (un écrivain ne tente le slot `n+1` qu'après avoir lu `0..n`, et les slots ne
sont jamais supprimés). Si une fenêtre B recoupe A avec A au slot `i` et B au slot `j > i`, B a lu le slot `i` avant
son `link` et voit le recouvrement. Aucune paire recouvrante de campagnes différentes ne coexiste dans la chaîne.
Cet argument vaut pour E3 contre E3 sur un registre unique ; il ne couvre pas les accès hors E3 (23.9).

**Même `campaign_id`, deux tentatives.** Une admission existante de la même campagne est réutilisable seulement si
son contenu sémantique est identique (campagne, fenêtre, engagement et son `content_hash`, réservation, attachment,
preuve de temps, hashs d'attestation, d'autorisation et de projection, `static_sources_digest`, identité de code,
liaison du registre), qu'aucune `CONSUMPTION` n'existe dans le registre pour ce `campaign_id` **et** qu'aucun Claim ni
aucun `ReadIntent` n'existe localement (le seul test local est insuffisant : un dossier copié le passerait). Sinon
`AlreadyInProgressOrConsumed` : arrêt avant tout appel d'E2. Si deux processus passent ces contrôles en parallèle,
E2 est exclusif par dossier et la `CONSUMPTION` est exclusive par `campaign_id` dans le registre : un seul des deux
atteint le `ReadIntent`, y compris pour une copie du dossier de campagne.

**Crash avant le Claim.** Au redémarrage, la campagne retrouve sa propre admission, rejoue les vérifications et la
réutilise si l'identité sémantique est inchangée. Un enregistrement relu après un crash est d'abord re-confirmé
durable par un `fsync` explicite du répertoire (permis pour une `RESERVATION` ou une `ADMISSION` relue, jamais pour
une `CONSUMPTION`). Si l'attestation a été remplacée, refus : l'admission reste et
réserve la fenêtre. Réutiliser une admission n'ouvre aucun accès ; seul le Claim d'E2 ouvre le droit. *(Précisé par
23.27.3 : la reprise ne rejoue jamais la comptabilité ; « Même `campaign_id`, deux tentatives » ci-dessus est inchangé
et compatible avec 23.27.2 et 23.27.4.)*

### 23.11 — Inventaire, déclarations, classification, attestation, autorisation

Séquence non circulaire. Chaque artefact est créé en exclusif et durable ; `_id` = hash sans horodatage,
`_content_hash` = hash du contenu complet avec horodatage, épinglé par le successeur.
1. **Inventaire A0** : calculé sans entrée humaine. Contient les sources **trouvées** dans les racines d'audit
   configurées (déclarées dans le fichier de configuration de root, 23.9 : répertoires `results/` des worktrees
   concernés, répertoires d'événements des plans, campagnes référencées par la chaîne du registre), la projection de
   recouvrement du registre, `static_sources_digest`, la **comptabilité des essais** (ci-dessous) et la version des
   règles. Les sources que seul l'humain connaît entrent uniquement par les déclarations (étape 2). Un répertoire
   d'audit manquant, un
   JSON illisible ou une clé inconnue refuse (lister **strict** ; `list_holdout_access_events` ignore les JSON invalides
   et ne peut pas fonder ce contrôle, 22.2-4). Les artefacts du dossier de la campagne courante sont exclus. En
   revanche, tout enregistrement du registre portant le `campaign_id` courant autre que ses propres `RESERVATION` et
   `ADMISSION` attendus (par exemple une `CONSUMPTION`, ou une seconde réservation) n'est **jamais** ignoré : c'est
   une condition d'arrêt. Un `campaign_dir_locator` introuvable ne bloque pas le test de recouvrement (la fenêtre est
   portée par l'enregistrement du registre lui-même) ; il rend la campagne « abandonnée » pour la comptabilité ; un
   répertoire d'audit **configuré** manquant, lui, refuse. *(L'exclusion « par dossier de la campagne courante » est
remplacée par 23.27.2 : absorption par `campaign_id` et par étage vérifié, doublons et enregistrements inattendus en
échec fermé. Les « campagnes référencées par la chaîne du registre » ne sont pas des racines d'audit configurées :
ce sont des sources dérivées, exclues de `scanned_roots` (23.27.3).)*
2. **Déclarations D1..Dn** : nominatives, versionnées, en slots denses, chacune liée à l'inventaire et à la précédente.
   Elles ne peuvent que durcir (une déclaration d'exposition passe la classe vers `RETROSPECTIVE_EXPOSED` ou
   `UNDETERMINED`), jamais assouplir une classe automatique. Une déclaration peut aussi repousser `t_sel` à une date
   plus tardive ; le `t_sel` effectif utilisé par F2 et par C est le maximum de celui de l'engagement et de ceux des
   déclarations, jamais une date plus ancienne.
3. **Classification C** : fonction pure de A0, des déclarations et des **preuves de chronologie** (engagement,
   réservation, `ReservationTimeProof`, `IngestionRecord`, `max(time)` de `S0` calculé, `t_sel` et `t_anchor`
   déclarés ou vérifiés), recalculée à chaque vérification. Le niveau de chronologie (23.3) en résulte et est inscrit
   dans l'attestation.
4. **Attestation T** : nominative, liée à C, à A0, à la tête des déclarations, à l'engagement, à l'attachment, à la
   projection de recouvrement et au préfixe de chaîne (`seq`, `content_hash`). Elle est périmée dès que l'un de ces
   éléments change. **Elle n'autorise rien.** *(Complété par 23.27.3 : elle épingle `inventory_content_hash`, qui couvre la
comptabilité des essais, et `inventory_id`.)*
5. **Autorisation d'acquisition** : décision humaine **distincte**, nominative, liée à T, à l'engagement, au `claim_id`
   (calculable depuis le plan), à la fenêtre, au mode, au SHA du code, au rapport de qualification, à la projection et
   au préfixe de chaîne. Seule elle déclenche l'admission.
6. **Vérification avant admission** : A0, D\* et C sont recalculés et doivent égaler T ; sinon refus. *(Complété par
   23.27.3 : `inventory_id`, `static_sources_digest`, projection et `inventory_content_digest` doivent aussi égaler ceux
   du A0 persisté attesté ; une comptabilité modifiée refuse, `ACCOUNTING_CHANGED`.)*

**Comptabilité des essais (reprise de 22.2-6).** L'inventaire et le `ClosingRecord` enregistrent : le nombre de
`ResearchRun`, de stratégies et de campagnes évalués (toutes les `RESERVATION`, `ADMISSION` et `CONSUMPTION` de la
chaîne du registre, **quelles que soient leurs fenêtres**, les campagnes V1 avec OOS et les nombres déclarés), le
nombre de réservations **abandonnées** (sans `ClosingRecord` terminal), de tentatives d'ingestion échouées et
d'engagements nuls. Une campagne dont le `ClosingRecord` est introuvable (localisation périmée, dossier déplacé) est
comptée comme abandonnée (conservateur). C'est une comptabilité de
multiple testing : aucune correction statistique n'est calculée ni aucun seuil fixé (hors périmètre, Human Gate).
*(Portée des compteurs, absence de double comptage et rôle du `ClosingRecord` remplacés par 23.27.5.)*

Trois décisions humaines distinctes : (1) attestation des expositions historiques ; (2) autorisation explicite d'une
acquisition irréversible ; (3) Human Gate de qualification scientifique d'un éventuel Champion (hors E3). L'identité
de l'attestant est déclarative : pas d'authentification forte, donc pas de non-répudiation.

### 23.12 — Acquisition du Claim par E2, inchangée

E2 reste le **seul** chemin d'acquisition et E3 le seul importeur d'E2 (test AST, 22.12.3). Le Claim reste la projection
à 14 clés du plan ; il ne porte ni l'admission, ni l'engagement, ni `S_H` : ces liens sont portés par le `ReadIntent`.
E3 appelle E2 elle-même, ne reçoit ni ne relit un Claim comme autorisation, et refait la vérification locale de 22.10
(sentinelle, verrou) avant le `ReadIntent`, puis une seconde fois immédiatement avant l'ouverture de `S_H` (23.17).
L'admission durable précède le Claim ; la `CONSUMPTION` (23.10) suit le retour durable d'E2 et précède le
`ReadIntent`. Après toute exception d'E2, aucun accès marché n'est autorisé. Un Claim sans `CONSUMPTION` (crash entre
les deux) est traité comme consommé : la campagne est close sans lecture (`EXECUTION_VOID_CLAIM_ONLY`) et une
`CONSUMPTION` de régularisation ne peut être publiée que par un acte humain.

### 23.13 — `ReadIntent`, `DataReceipt`, `ValidationRun` OOS, `HoldoutAccessEvent`, `ClosingRecord`

Tous créés en exclusif et durables, chacun épinglant le `content_hash` de son prédécesseur dans la chaîne causale
ci-dessous, sauf la `ValidationRun` OOS dont le schéma est fixe : elle est liée par son identifiant déterministe et
par son `validation_run_record_hash` (23.4) épinglé dans le `ClosingRecord`.
- **`ReadIntent`** (`<campaign_dir>/read_intent.json`, un seul par campagne) : écrit après la `CONSUMPTION` durable et
  avant toute ouverture de `S_H`.
  Contient `claim_id`, hash sémantique et `seq` de l'admission, de la réservation et de la `CONSUMPTION`, liaison du
  registre, `commitment_id`
  et `commitment_content_hash`, `attachment_id` et `attachment_content_hash`, `content_hash` de la preuve de temps,
  hashs d'attestation et d'autorisation, mode, fenêtre, `end_boundary`, coûts, identité du code, `oos_parameters`,
  hash de provenance, `research_snapshot_id`, `holdout_snapshot_id` attendu, répertoire d'événements du plan,
  `created_at`.
  `read_intent_id = SHA256(canonical_json({claim_id, admission_id, commitment_id, attachment_id,
  read_intent_semantics_version}))`.
- **`DataReceipt`** (`<campaign_dir>/data_receipt.json`) : `holdout_bytes_sha256`, taille, `engine_input` (23.5), bracket
  `fstat`. Écrit avant le lancement du moteur ; son échec empêche le lancement.
- **`ValidationRun` OOS** : schéma existant, écriture exclusive durable via un écrivain additif sous
  `<campaign_dir>/validations/<oos_validation_run_id>.json` (`save_validation_run` reste `save_atomic`, inchangé). Identifiant déterministe `oos_validation_run_id = "oos_" +
  sha256(campaign_id + ":" + claim_id)[:32]` (hex minuscule), indépendant de `gate_v_v2_validation_run_id`
  (WF, MC, PS, inchangé).
- **`HoldoutAccessEvent` canonique** (Décision 13, **extension additive**) : champs `Optional` à défaut `None`
  `campaign_id`, `final_holdout_claim_id`, `gate_v_preregistration_id`, `gate_v_preregistration_content_hash`, plus
  `holdout_access_event_content_hash` stocké, calculé par la formule de la Décision 13 (inchangée). **Les champs
  additionnels ne sont sérialisés que lorsqu'ils sont non nuls**, par `save_holdout_access_event` comme par l'écrivain
  canonique : la sortie d'un événement legacy reste donc identique octet pour octet à celle d'aujourd'hui. Les
  événements legacy restent lisibles. Un **lister strict** additif (échec sur JSON illisible, clé inconnue ou hash
  faux) fonde le contrôle d'exposition : un événement sans aucun champ additionnel est accepté comme événement legacy
  (sans hash) ; dès qu'un champ additionnel est présent, le hash est obligatoire et vérifié.
  `load_holdout_access_event`, `list_holdout_access_events` conservent leur signature et leur comportement. Le
  constructeur `build_holdout_access_event` reçoit un complément additif (ou un constructeur frère) pour les champs
  additionnels et le hash (`dataset_split.py` est donc modifié de façon additive, 23.23). **Limite** : un code
  antérieur à cette Décision (autre worktree ou branche) fait `cls(**data)` puis `None` sur `TypeError`
  (`load_tolerant`) et ignore donc silencieusement un événement étendu ; seul le code à jour et un worktree propre
  (23.2) sont garantis de le voir. `event_id = "hoe_" + sha256(claim_id + ":" + read_intent_id)[:32]` ; `accessed_at` = `created_at`
  du `ReadIntent`, mot pour mot ; `validation_run_id` = identifiant OOS déterministe (ou `null` si aucune `ValidationRun` n'existe) ;
  `reason` = `"gate_v_final_holdout_oos_v1;read_intent=" + read_intent_id + ";holdout_snapshot=" + <identifiant de
  S_H>` (constante de version plus deux identifiants : l'identité de `S_H` entre ainsi dans le hash de la Décision 13
  sans changer le schéma) ; `locked_state = "locked"` ; `dataset_snapshot_id` de l'événement = `S0` (champ legacy, comme
  dans l'événement construit par `run_oos_validation`) : ce n'est pas le snapshot consulté, et la règle d'attribution
  de 23.5 s'y applique aussi ; `accessed_at` désigne l'instant d'intention de lecture (il précède l'accès réel :
  minorant du début d'accès, non majorant) ; le nom de fichier existant devient une fonction déterministe d'artefacts persistés. Le répertoire est le répertoire d'événements du plan de
  split (convention `holdout_access/` du répertoire du plan), fourni par l'appelant, consigné dans le `ReadIntent` et
  contenu dans les racines d'audit configurées (23.11). Écriture par la primitive de publication par lien
  (`tmp + fsync + os.link + fsync`, complète ou absente : aucun fichier canonique tronqué n'est possible) ;
  `FileExistsError` = « déjà écrit » : relecture stricte et comparaison du hash, échec fermé s'il diffère. Un seul
  événement par accès physique ; **l'événement construit par `run_oos_validation` (uuid4, horloge) est jeté** ;
  le **timing de la Décision 13 est conservé** (événement après la `ValidationRun` ; le `ReadIntent` est le
  write-ahead séparé).
- **`ClosingRecord`** (`<campaign_dir>/final_holdout_closing_record.json`) : marqueur de validation. Liste les hashs de
  tous les artefacts de la chaîne, `result_attribution` (identités de 23.5), `provenance_residuals`, `terminal_state`
  (`CLOSED_COMPLETE` ou `EXECUTION_VOID_<cause>`, seule graphie admise). Pour un état `EXECUTION_VOID_<cause>` sans
  `DataReceipt`, les champs correspondants valent `null` avec la cause explicite. Si un `ReadIntent` existe, un
  événement canonique est écrit avant le `ClosingRecord`, même sans `ValidationRun` (accès possible). **Aucun verdict.**
- Chaîne causale (liens par hash) : engagement → réservation → preuve de temps → attachment → attestation →
  autorisation → admission → Claim (E2) → `CONSUMPTION` → `ReadIntent` → `DataReceipt` → `ValidationRun` OOS →
  événement → `ClosingRecord`.
- **Chemins et versions sémantiques** (noms normatifs, relatifs à `<campaign_dir>` sauf mention) : `prospective_commitment.json`
  (`gate_v_prospective_commitment_v1`), `s0_provenance_declaration.json` (`gate_v_s0_provenance_declaration_v1`),
  `reservation_time_proof.json` (`gate_v_reservation_time_proof_v1`), `holdout_snapshot_attachment.json`
  (`gate_v_holdout_attachment_v1`), `commitment_void_record.json` (`gate_v_commitment_void_v1`),
  `exposure/inventory_<content_hash>.json` (`gate_v_exposure_inventory_v1`), `exposure/declaration_<seq>.json`
  (`gate_v_exposure_declaration_v1`), `exposure/attestation.json` (`gate_v_exposure_attestation_v1`),
  `acquisition_authorization.json` (`gate_v_acquisition_authorization_v1`), `read_intent.json`
  (`gate_v_read_intent_v1`), `data_receipt.json` (`gate_v_data_receipt_v1`), `final_holdout_closing_record.json`
  (`gate_v_closing_record_v1`) ; registre : `admissions/admission_<seq>.json` (`gate_v_registry_admission_v1`) ; coffre :
  `<coffre>/<commitment_id>/ingestion_record.json` (`gate_v_ingestion_record_v1`),
  `<coffre>/<commitment_id>/attempt_<n>.json` (`gate_v_ingestion_attempt_v1`) et `<coffre>/<commitment_id>/s_h.csv`
  (octets de `S_H`, sans version de schéma). Les
  attestations successives suivent la règle de supersession par slots denses des déclarations.
- **Miroir Manifest** (champs 13-17) : slice optionnelle, monotone `None → id`, jamais autorité d'exclusivité ; le
  Manifest n'importe aucun module Claim. Tant qu'elle n'est pas spécifiée plus finement, E3 n'écrit pas ces champs et
  le `ClosingRecord` fait foi.

### 23.14 — Lecture unique du holdout et vérification des octets exploités

- **Avant le Claim** : aucune lecture des octets de `S_H` (hors l'ingesteur, borné par 23.7). `S0` peut être lu,
  vérifié et analysé (donnée de recherche) ; **les octets de `S0` qui construisent le DataFrame transmis au moteur sont
  revérifiés (hash) dans le même buffer que celui qui sert à les parser**, jamais lus une première fois pour un hash
  puis relus pour l'analyse.
  Les contrôles de métadonnées de `S_H` se limitent à `lstat` (fichier régulier, ni lien symbolique ni point de
  reparse) et à la taille, jamais aux octets.
- **Après le `ReadIntent`**, une lecture unique : `lstat`, `os.open`, `fstat` comparé à `lstat`, lecture exacte de la
  taille dans un buffer avec SHA-256 incrémental, `fstat` final inchangé, comparaison du hash avec l'attachment, puis
  parsing **depuis ce même buffer** via une aide additive `engine.load_data_from_bytes`, dont l'équivalence bit à bit
  avec `engine.load_data` est testée sur des fixtures. Scénario interdit : lire pour hasher, créer le Claim, relire pour
  exécuter.
- **Hash incorrect** : Claim brûlé, moteur non lancé, état `EXECUTION_VOID`.
- **Contrôles du DataFrame** : colonnes et en-tête égaux à `S0` ; `time` strictement croissant et unique (le moteur
  appelle `searchsorted` sans le vérifier) ; sans `NaT` ; première barre de `S_H` strictement postérieure à la
  dernière de `S0` ; règle de couverture engagée respectée ; nombre de lignes de contexte au moins égal à
  `required_warmup`. Troncature à `time_paris < end` avant l'appel ; le buffer est libéré après le parsing.
- Un fichier remplacé entre `lstat` et lecture est détecté par la comparaison `fstat` ; le hash du buffer reste
  l'autorité d'identité du contenu, le chemin n'en est jamais une. Une limite mémoire (taille maximale déclarée) est une
  décision opérationnelle (23.24).

### 23.15 — Bornes `[start, end)` et adaptateur moteur

- `FINAL_HOLDOUT = [start, end)`. `run_oos_validation` est appelée **inchangée**, avec
  `run_backtest_fn = functools.partial(engine.run_backtest, end_boundary="exclusive", initial_capital=…, spread=…,
  slip_in=…, slip_out=…)` : `run_oos_validation` appelle `run_backtest_fn(df, strategy, params, start_date=,
  end_date=)`, les arguments du `partial` s'ajoutent sans conflit. Le défaut du moteur reste inclusif ; le
  comportement de V1 est inchangé.
- Les bornes sont des ISO-8601 offset-aware ; une chaîne naïve est refusée (le moteur appellerait `tz_localize` et
  lèverait sur les heures DST ambiguës ou inexistantes).
- Le contexte avant `start` reste visible pour `prepare()` ; le moteur n'exécute aucune opération avant
  `exec_start_idx`. Si moins de `required_warmup` lignes précèdent `start`, l'exécution démarrerait plus tard en
  silence : E3 le refuse (23.14).
- **Tests aux bornes** (barres synthétiques) : `start−pas`, `start`, `start+pas`, `end−pas`, `end`, `end+pas` ; même
  instant exprimé en `Z` et en `+02:00` ; transitions DST de Paris au voisinage de la fenêtre engagée, avec au moins celles du 2025-03-30 et du 2025-10-26
  comme vecteurs fixes ; borne naïve refusée ;
  temps dupliqué ou non croissant refusé ; contexte égal à `warmup` puis à `warmup−1` ; résultat exclusif égal au
  résultat sur un DataFrame pré-tronqué ; aucune barre `≥ end` n'atteint `strategy.prepare()` (espion) ; résultats
  inclusif et exclusif identiques sans barre à `end`, différents avec une barre à `end` ; tests V1 inchangés.

### 23.16 — Paramètres OOS pré-engagés, coûts, warm-up, readiness, identité du code

| Élément | Persisté aujourd'hui | Manque | Règle E3 |
|---|---|---|---|
| `initial_capital` | `global_params` de la config d'optimisation, `config_used.json` (job) ; lu par Monte-Carlo | pré-enregistrement, plan, empreinte (Décision 7), `ValidationRun` | engagé ; refus si absent |
| `spread`, `slip_in`, `slip_out` | `global_params` ; défauts silencieux de l'optimiseur | tout le chaînage V2 | engagés, valeurs explicites ; aucun défaut |
| Version du moteur | `ENGINE_VERSION = "1.0"` (constante manuelle), `ResearchRun.engine_version` | liée au contenu du code | insuffisante seule ; SHA Git et hashs de fichiers engagés |
| Version du code | `ResearchRun.git_sha` (optionnel) | non garanti propre | arbre propre exigé ; SHA engagé |
| Identité de la stratégie | `strategy_name` (pré-enregistrement) | `strategy_module`, hash du source | engagés |
| `base_params` | dans l'empreinte (Décision 7) | — | déjà épinglé |
| Paramètres OOS | aucune règle dans les modules lus | tout | `oos_parameters` littéraux, règle `LITERAL_PREDECLARED` |
| Warm-up | calculé à l'exécution (`required_warmup`) | non persisté | valeur engagée et vérifiée |
| Readiness | `readiness_spec` (empreinte) ; appliquée aux bornes de folds du Walk-Forward | non appliquée par `run_oos_validation` | pré-contrôle pur en phase P, **avant la réservation** : `resolve_state_ready_boundary` ne doit pas ajuster `start` ; pour `end`, la règle exacte est alignée sur celle que le Walk-Forward applique à la fin des folds de test (à confirmer par un test RED en E3-I) ; sinon refus |

La Décision 7 n'est pas modifiée (changer l'empreinte changerait tous les `campaign_id` V2). Les éléments manquants sont
épinglés dans l'engagement. Les coûts engagés sont comparés à la configuration source du job dont le hash est épinglé
dans l'engagement ; leur identité avec les coûts effectivement utilisés par les folds Walk-Forward n'est pas prouvée
par les artefacts V2 (limite, 23.25). Les contrôles purement déterministes (readiness, valeur de `required_warmup`,
bornes offset-aware, lignes de contexte de `S0`) sont exécutés en phase P, avant la réservation, afin de ne pas brûler
une fenêtre réservée pour une erreur prévisible. **Si une donnée indispensable à l'équivalence WF/OOS est absente, le refus est explicite ;
aucun défaut silencieux n'est inventé.** Aucune règle de dérivation d'un jeu de paramètres final unique à partir des
preuves par fold n'a été trouvée dans les modules lus ; la correspondance entre `oos_parameters` et les preuves
WF/MC/PS est donc **déclarée et référencée**, vérifiée seulement pour la cohérence avec `base_params` et le schéma de
la stratégie, et relève du Human Gate.

### 23.17 — Séquence normative d'E3 et points de non-retour

**Phase P — avant `ws`** : P1 mode et UID ; P2 autorité du registre ; P3 lecture, vérification et analyse de `S0`
(hash, `max(time) < ws`, lignes de contexte ≥ `required_warmup`) ; P3 bis contrôles déterministes : readiness,
valeur de `required_warmup`, bornes offset-aware (23.16) ; P3 ter `S0ProvenanceDeclaration` créée (23.7) ; P4 D5
complète ; P5 engagement créé (23.4) ; P6
**`RESERVATION`** durable de `W` — **point de non-retour R : la fenêtre est protégée définitivement pour cette
campagne** ; P7 preuve de temps (`ReservationTimeProof`) sur l'enregistrement de réservation, vérifiée, avec
`borne + marge ≤ ws`.

**Phase I — après `we`** : I1 ingestion de `S_H` par l'ingesteur, `IngestionRecord` ; I2 attachment (23.8).

**Phase E — exécution** :
0. mode et UID ; 1. autorité du registre ; 2. preuve de temps revérifiée hors ligne ; 3. lecture, vérification et
analyse de `S0` (hash, `max(time) < ws`, lignes de contexte ≥ `required_warmup`) ; 4. pré-contrôle de readiness ;
5. valeur de `required_warmup` égale à celle engagée ; 6. provenance de niveau 1 ; 7. chargement strict des sources,
D5 ; 8. inventaire, déclarations, classification, attestation valide ; 9. autorisation ; 10. métadonnées de `S_H`
(`lstat`, taille, type de snapshot) ; 11. **`ADMISSION`** durable (23.10) ; 12. **E2 : Claim durable** — **point de
non-retour 1 : le droit de la campagne est consommé** ; 12 bis. **`CONSUMPTION`** durable dans le registre (23.10),
verrou d'exclusivité par `campaign_id` : sans elle, aucune étape suivante ; 13. recontrôle : autorité du registre,
sentinelle, verrou (22.10), admission propre et chaîne dense, **attestation, tête des déclarations, autorisation et
`static_sources_digest` revérifiés** (sans jamais comparer la comptabilité des essais, 23.27.3) ; 14. **`ReadIntent`** durable — **point de non-retour 2 : lecture possiblement commencée, fenêtre traitée comme
exposée** ; 14 bis. second recontrôle de la sentinelle et du verrou **immédiatement avant l'ouverture de `S_H`**
(22.10) : en cas d'échec, aucune lecture n'a lieu et le `ReadIntent` existant est traité comme exposé (conservateur) ;
15. lecture unique, contrôles, `DataReceipt` ; 16. `run_oos_validation` via l'adaptateur — **point de non-retour 3 :
résultat observé** ; 17. `ValidationRun` OOS, événement canonique, `ClosingRecord`. Chaque étape exige le retour
durable de la précédente.

### 23.18 — Crash, états dérivés et récupération humaine

Règle générale : **aucune suppression de Claim, aucune seconde acquisition, aucun retry du `FINAL_HOLDOUT`, aucune
relecture, aucun nettoyage automatique d'une preuve de consommation.** Les états sont dérivés des artefacts présents et
aucun ne signifie « aucun accès prouvé ».

| Transition | Prouvé durablement | Seulement inféré | Perdu | Restaurable depuis des artefacts persistés | Réexécution |
|---|---|---|---|---|---|
| Engagement → `RESERVATION` → preuve de temps | engagement, puis réservation durable | — | — | preuve de temps rejouable ; sans preuve valide, la réservation reste et la campagne est inutilisable | permise (preuve) |
| Inventaire → attestation → autorisation | rien de consommé | — | — | recalcul | permise |
| Autorisation → admission | autorisation | — | — | — | permise |
| Admission durable → Claim | admission, fenêtre réservée | aucune lecture | — | réutilisation sémantique (23.10) | permise (E2) |
| Claim → `CONSUMPTION` | Claim | absence de lecture (déduction conditionnelle) | — | `CONSUMPTION` de régularisation, acte humain, sans lecture | **interdite** |
| `CONSUMPTION` → `ReadIntent` | Claim, `CONSUMPTION` | absence de lecture (déduction conditionnelle) | — | — | **interdite** |
| `ReadIntent` → `DataReceipt` | intention | lecture possible | contenu lu | — | **interdite** |
| `DataReceipt` → `ValidationRun` | octets lus (hash) | — | résultat | rien d'autre que le reçu | **interdite** |
| `ValidationRun` → événement | `ValidationRun` | — | — | événement déterministe, sans marché | **interdite** |
| Événement → `ClosingRecord` | événement | — | — | clôture | **interdite** |

États dérivés : `RESERVED`, `RESERVATION_STALE`, `ADMITTED`, `ADMITTED_STALE`, `CLAIM_ONLY`, `CONSUMED`, `CONSUMED_UNCONFIRMED` (consommation visible mais non
confirmée durable, traitée comme `CONSUMED`), `INTENT_RECORDED`,
`INTENT_UNREADABLE` (`ReadIntent` tronqué ou illisible : lecture possiblement commencée), `RECEIPT_RECORDED`,
`RESULT_PRESENT_NOT_CLOSED`, `CLOSED_COMPLETE`, `EXECUTION_VOID_<cause>`, `INCONSISTENT` (dont : Claim sans
admission, `ADMISSION` sans `RESERVATION` correspondante, `CONSUMPTION` sans `ADMISSION`, deux enregistrements du même
type pour un `campaign_id`, trou dans la chaîne, artefact contradictoire). Un `ReadIntent` sans événement terminal est traité comme exposé. Un crash entre la
lecture physique et la création de l'événement est traité comme accédé. La reconstruction d'un événement manquant est
un acte humain depuis des artefacts persistés, écrit au même nom donc exclusif ; sans `ValidationRun`, elle porte un
`reason` explicite. Récupération d'une publication d'enregistrement du registre (crash à chaque étape) : matrice de
23.10 ; un trou de numérotation après coupure est une corruption qui arrête tout `REAL` jusqu'à décision humaine.

### 23.19 — Courses et concurrence

Deux campagnes distinctes sur des fenêtres recouvrantes, depuis deux répertoires de job distincts, se coordonnent
**uniquement** par le registre unique (23.9, 23.10). Deux processus pour le même `campaign_id`, y compris depuis un
dossier de campagne copié ou restauré : 23.10. Au plus un lecteur par `campaign_id` : la `CONSUMPTION`, exclusive par
`campaign_id` dans le registre, précède tout `ReadIntent` ; le Claim et le `ReadIntent` ne sont exclusifs que par
dossier. Un script qui contourne E3 reste hors modèle (23.9).

### 23.20 — Obligations de test (toutes synthétiques ; aucun test ne consulte le véritable `FINAL_HOLDOUT`)

**Exécutables localement (L)** (avec le profil `SIMULATED_DURABLE`, fautes de `fsync` injectées, sous Windows comme
sous Linux) : deux engagements rivaux sur la même fenêtre ou une fenêtre recoupante (la seconde `RESERVATION` est
refusée, donc non ancrable, y compris avec des `split_plan_id` différents) ; jeton de temps obtenu sur l'engagement
seul, ou réservation publiée après la borne de la preuve : non recevable ; `ADMISSION` sans `RESERVATION`
correspondante (même campagne, même `commitment_content_hash`, même fenêtre) refusée ; deux réservations de la même
campagne avec des engagements différents refusées ; copie du dossier de campagne sous une autre racine (seconde
`CONSUMPTION` refusée, aucun second `ReadIntent`, aucune seconde lecture) ; réservation abandonnée comptée dans la
comptabilité des essais, y compris avec `ClosingRecord` introuvable ; garde d'attribution (aucun consommateur ne lit
`ValidationRun.dataset_snapshot_id` ni `HoldoutAccessEvent.dataset_snapshot_id` comme le snapshot consulté d'une
campagne prospective) ; sortie sérialisée d'un
événement legacy identique octet pour octet après l'extension ; événement canonique complet ou absent après crash ;
lister strict acceptant un événement legacy sans hash et refusant un événement étendu au hash faux ; seconde
`CONSUMPTION` de même contenu refusée (aucune idempotence) ; `REBIND` et chaîne d'`instance_id` ; `ADMITTED_STALE`,
`RESERVATION_STALE` et `REGISTRY_CONTENTION` ; témoin de tête manquant ou en retard (progression arrêtée) et
restauration plus ancienne détectée par le témoin ; engagement ancré avant la fenêtre et snapshot acquis après ; snapshot impossible à
connaître à l'engagement ; deux copies de registre avec le même `registry_id` ; deux worktrees et une seule autorité ;
admission concurrente pendant la validation de l'attestation ; deux admissions simultanées du même `campaign_id` ;
crash après admission durable avant Claim ; slot visible non durable (fsync de répertoire simulé en échec) ; deux
attachments `S_H` ; premier `S_H` incorrect (engagement nul) ; snapshot valide d'instrument erroné (écho différent) ;
source sans preuve suffisante de timeframe ; `S0` qui chevauche la fenêtre ; décalages UTC et DST ; engagement
temporel non vérifiable ; exécution refusée avant Claim pour chaque précondition manquante ; mode synthétique de bout
en bout avec faute injectée à chaque point ; coûts WF/OOS manquants ou divergents ; fichiers supplémentaires dans
`campaign_dir` sans effet sur D5 et E2 ; le module d'exécution d'E3 seul importeur d'E2 (AST) ; ingesteur sans import d'analyse (AST) ;
aucune ouverture des octets de `S_H` avant le Claim (espion d'ouvertures) et une seule ensuite ; équivalence
`load_data_from_bytes` ; tests aux bornes de 23.15 ; V1 et suite existante inchangés ; processus multiples réels
avec barrière pour les admissions (fenêtres identiques, incluses, partielles, adjacentes).

**À démontrer sur la cible (Q, non démontrables localement)** : exclusivité multiprocessus sur le volume réel ;
comportement de `link` et de `fsync` de répertoire ; survie à une coupure d'alimentation réelle ; permissions et
cloisonnement du coffre ; liaison physique du registre ; comportement sous OCI.

### 23.21 — Portes de qualification `REAL` (aucune n'est remplie à la date de cette Décision)

1. Hôte Linux, volume local, liste de systèmes de fichiers acceptés.
2. Test de coupure d'alimentation réelle sur le volume cible.
3. Comportement de `link` et de `fsync` de répertoire démontré sur ce volume.
4. Test d'exclusivité multiprocessus sur ce volume.
5. Compte de service, permissions et cloisonnement du coffre démontrés.
6. Adaptateur de fournisseur non interactif avec écho de niveau 1 vérifié.
7. Autorité de temps choisie, liste de confiance committée, outil de vérification qualifié.
8. Procédure de sauvegarde et cérémonie `REBIND` documentées.
9. Liaison physique du registre démontrée (une copie est refusée ; une restauration est détectée grâce au témoin
   de tête copié hors de l'hôte).
10. Comportement sous OCI démontré, si OCI est la cible.
11. Répétition générale de bout en bout en mode `SYNTHETIC` sur la machine cible, avec coupure et reprise à chaque
    point de 23.18.
12. Rapport de qualification nominatif, nommant le SHA `X` du code qualifié.

Aucune qualification n'est fictive ni supposée. Le passage de `REAL_FINAL_HOLDOUT_ENABLED` à `True` est un commit
délibéré, relu, postérieur aux douze portes. **Chaîne de commits `X → R → B`** : le rapport nomme le SHA `X` du code
qualifié ; il est ajouté au dépôt par un commit `R`, enfant direct de `X`, dont le seul diff est le fichier du
rapport ; la bascule est un commit `B`, enfant direct de `R`, dont le seul diff est le passage de la constante à
`True`. La vérification `REAL` contrôle ces deux diffs (`X → R` : le rapport seul ; `R → B` : la constante seule) et
que le SHA courant est `B`. Le rapport ne contient donc jamais son propre SHA. Tout engagement est créé après `B` et
épingle le SHA de `B` (égalité exacte, 23.4) ; toute modification ultérieure du dépôt, y compris documentaire, change
le SHA courant et invalide l'engagement (conservateur).

### 23.22 — Amendements aux décisions antérieures (additifs, traçables)

| Décision | Amendement |
|---|---|
| 2 | Ordre inchangé ; les étapes 8-10 sont précisées par 23.17 |
| 9 | Primitif du Claim inchangé ; une publication `tmp + fsync + os.link + fsync` est ajoutée pour les enregistrements du registre et pour l'événement canonique seulement. Le support filesystem ciblé de la Décision 9 (Windows et Linux locaux) reste vrai pour le Claim ; E3 en mode `REAL` est restreint à Linux, ce qui est une restriction d'usage et non une modification |
| 11 | Étapes 1-9 inchangées ; les phases P et I et les étapes 0-11 d'E3 (23.17) précèdent toute la séquence d'acquisition d'E2 ; la `CONSUMPTION` et le `ReadIntent` suivent son retour durable |
| 13 | Extension additive de l'événement (champs `Optional` sérialisés seulement s'ils sont non nuls, donc sortie d'un événement legacy identique octet pour octet ; hash stocké ; lister strict ; `event_id` et nom de fichier déterministes ; écriture par publication par lien, complète ou absente) ; timing conservé ; `ValidationRun` OOS écrite en exclusif avec identifiant déterministe ; le miroir Manifest de 22.12.6 est explicitement reporté (le `ClosingRecord` fait foi) |
| 14 | Inchangée ; les `ValidationAssessment` OOS consomment la `ValidationRun` OOS et la règle d'attribution de 23.5 s'applique |
| 16 | Disposition portable inchangée ; fichiers additionnels dans `campaign_dir` ; registre et coffre **hors** de `results/job_xxx/` |
| 22.2 | Le « porteur exact » du contrôle d'exposition est résolu : artefacts distincts (inventaire, déclarations, attestation), référencés par hash |
| 22.12.1 | Le contrôle d'exposition précède l'admission, puis E2 |
| 22.12.4 | Portée précisée pour `S0` (analysable et vérifiable avant le Claim, car donnée de recherche) et resserrée pour `S_H` (unique lecture après le `ReadIntent`, 23.5) ; le Claim n'atteste pas `S_H` |
| 22.12.6 | Événement canonique et `ClosingRecord` précisés ; miroir Manifest reporté |

### 23.23 — Compatibilité E1/E2 et contrats préservés

- E1 : les 14 clés, `claim_id` et `claim_content_hash` (Décision 10) et toutes les fonctions pures sont inchangés.
- E2 : l'API, la séquence 22.6 et `save_exclusive` sont inchangés.
- Pré-enregistration, `scope_key`, `campaign_protocol_fingerprint`, `campaign_id`, Plan V2, Manifest V2 et D5 : inchangés.
  `validate_gate_v_campaign_plan_v2_sources` ne contrôle que l'égalité des identifiants et la chronologie des
  zones ; un `FINAL_HOLDOUT` futur est donc compatible (à confirmer par un test RED d'implémentation).
- V1, `results/job_xxx/`, moteurs, stratégies et artefacts historiques : inchangés. `validation_oos.py`,
  `validation_run.py` et `engine.run_backtest` ne sont pas modifiés (seule l'aide additive du chargeur est ajoutée).
  **Modifications additives futures, signalées** : `dataset_split.py` (champs `Optional` de `HoldoutAccessEvent`
  sérialisés seulement s'ils sont non nuls, complément du constructeur, lister strict, écrivain par publication par
  lien) et `atomic_json_store.py` (primitive de publication par lien, E3-C) ; aucune n'altère le contrat de lecture
  existant ni la sortie d'un événement legacy ; seul un code antérieur à cette Décision ignore les événements étendus
  (23.13).

### 23.24 — Décisions opérationnelles encore ouvertes (aucune valeur inventée ici)

**Aucune de ces valeurs n'a de défaut** : une valeur absente ou nulle refuse `REAL`.

Nombre maximal de tentatives de publication par appel dans le registre ; chemin canonique, compte de service et liste des hôtes du registre ; longueur de la fenêtre prospective et date `ws` ;
marge entre l'ancrage et `ws` ; choix de l'autorité de temps (RFC 3161 ou OpenTimestamps) ; support du témoin de
tête copié hors de l'hôte ; nombre maximal de tentatives d'ingestion ; échéance d'ingestion après `we` ; règle de
couverture ; limite mémoire du chargeur ; permissions exactes du registre, de sa configuration et du coffre ; liste
des systèmes de fichiers acceptés ;
marge de fuseau pour les fenêtres sans offset vérifié (à défaut : `UNDETERMINED`) ; règle de sélection des
`oos_parameters` autre que `LITERAL_PREDECLARED` ; fournisseur et adaptateur d'acquisition ; politique de
sauvegarde du registre ; chemin normatif du fichier du rapport de qualification (fixé par la slice E3-Q, nécessaire à
la vérification `X → R → B` de 23.21) ; spécification fine du miroir Manifest.

### 23.25 — Limites résiduelles et absence de verdict

Travaux manuels non enregistrés ; `run_oos_validation` publique ; `results/` local et non versionné ; plusieurs hôtes
indépendants ; administrateur root ; connaissance de marché humaine pendant la fenêtre ; information dérivée du hash et
de la taille ; provenance de niveau 2 déclarée et de niveau 3 impossible à prouver ; `oos_parameters` sans règle de
dérivation officielle ; identité non prouvée entre les coûts engagés et ceux effectivement utilisés par les folds
Walk-Forward (les artefacts V2 ne les portent pas) ; blocage définitif d'une fenêtre par une réservation abandonnée
(conservateur, comptabilisé) ; enregistrements du registre postérieurs au dernier témoin de tête et non référencés,
perdus par une restauration complète de la machine ; code antérieur à cette Décision qui ignore les événements
étendus ; peu de trades possibles sur une fenêtre courte (la longueur relève de la policy). **E3 n'écrit
jamais de verdict `GATE V`, de Champion, de « robuste » ni de qualification scientifique.**

### 23.26 — Découpage TDD indicatif

E3-A modèles purs et classification ; E3-B intervalles et inventaire strict ; E3-C primitive de publication durable ;
E3-D registre et admissions ; E3-E engagement, preuves de temps, attachment et nullité ; E3-F ingesteur et provenance ;
E3-G événement canonique, `ValidationRun` exclusive, identifiant OOS ; E3-H chargeur par octets ; E3-I adaptateur
moteur ; E3-J orchestrateur et mode `SYNTHETIC` ; E3-K diagnostic en lecture seule ; E3-L miroir Manifest (optionnel) ;
E3-Q qualification (cible). Chaque tranche : RED, GREEN, revue, suite existante verte. *(Périmètres précisés par
23.27.7.)*

### 23.27 — Addendum E3-A (2026-10-13) : alignement normatif de 23.3, 23.10 et 23.11

**Statut.** Cet addendum est un amendement **normatif** à la Décision 23. Il aligne le texte sur le design E3-A
(modèles purs et classification d'exposition), verrouillé sous réserve de revue de l'addendum. **E3-A reste NON
IMPLÉMENTÉ**, le mode `REAL` reste désactivé et non qualifié, `GATE V` reste non passée. Aucune identité ni aucun
contrat d'E1 ou d'E2, aucune formule des Décisions 13 et 22, n'est modifié.

**Hiérarchie.** En cas de divergence entre 23.27 et une clause listée ci-dessous, **23.27 prévaut**. Les clauses
d'origine ne sont pas réécrites (traçabilité) : une note de renvoi les signale. **[R]** = clarification rédactionnelle,
**[N]** = changement réellement normatif.

| Clause d'origine | Traitement | Nature |
|---|---|---|
| 23.3, définition de `E` | complétée (exception des enregistrements attendus de la campagne courante) | [R] |
| 23.10, « Définitions », phrase « Pour une campagne `FRESH_UNEXPOSED_DECLARED`, cet ensemble est vide » | remplacée par 23.27.1 | [R] + [N] |
| 23.10, étape 2 (`ADMISSION`) et étape 5 (nouvelle tentative après conflit de slot) | complétées par 23.27.4 | [N] |
| 23.10, étape 8 | précisée : la comptabilité n'y est jamais comparée | [R] |
| 23.10, « Instant de péremption », dernière phrase | remplacée par 23.27.4 | [N] |
| 23.11, étape 1, exclusion « par dossier de la campagne courante » | remplacée par 23.27.2 | [N] |
| 23.11, étape 1, « racines d'audit configurées … campagnes référencées par la chaîne du registre » | précisée par 23.27.3 (`scanned_roots` = racines statiques seulement) | [N] |
| 23.11, étapes 4 et 6 | complétées par 23.27.3 | [R] + [N] |
| 23.11, « Comptabilité des essais » | remplacée par 23.27.5 | [N] |
| 23.6, marge d'ancrage | précisée par 23.28 : une marge ≤ 0 est `UNVERIFIED` (F4) | [N] |
| 23.10, « Crash avant le Claim » | précisé par 23.27.3 : la reprise ne rejoue jamais la comptabilité | [N] |
| 23.17, étape 13 | complétée par 23.27.3 (comparaison d'`inventory_id`, jamais de la comptabilité) | [N] |
| 23.26, découpage | précisé par 23.27.7 | [R] |

#### 23.27.1 — Ensemble pertinent et fraîcheur (A1)

- Une classification `FRESH_UNEXPOSED_DECLARED` **n'implique pas** l'absence de réservations ou d'admissions rivales.
- *Ensemble pertinent* : les sources de l'inventaire dont le verdict de recouvrement n'est pas `NO_OVERLAP` (donc les
  recoupantes, les inconnues et les non résolues). Pour une campagne `FRESH_UNEXPOSED_DECLARED`, il ne contient **aucune
  source exposante ni inconnue** ; il peut contenir des `RESERVATION` ou `ADMISSION` d'**autres** campagnes qui
  recoupent `W`.
- Une réservation ou une admission rivale recoupante **n'est pas une exposition scientifique** (aucune donnée n'a été
  lue) : elle n'altère pas la classe, mais elle **interdit l'admission** (refus `OVERLAPPING_REGISTRATION`). L'autorité
  d'exclusivité reste le registre (23.10, E3-D) ; le refus d'E3-A en est le reflet informatif.
- Les plans de split **jamais utilisés** sont informatifs : ils ne sont pas des findings de l'inventaire, n'entrent ni
  dans `inventory_id`, ni dans les digests, ni dans l'ensemble pertinent ; E3-B les consigne dans une liste informative
  du A0 persisté. Un plan qui a servi est une exposition par ses événements, `ValidationRun` ou jobs.
- Les enregistrements attendus de la campagne courante, selon son étage (23.27.2), n'en font pas partie.

#### 23.27.2 — Campagne courante, étage et enregistrements propres (A3, A5)

- **L'exclusion par chemin de dossier est supprimée** : une copie ou une restauration du dossier de campagne conserve
  son `campaign_id`. L'inventaire liste **tous** les enregistrements portant le `campaign_id` courant, où qu'ils soient.
  `campaign_id` est requis (chaîne non vide) pour tout enregistrement `RESOLVED` de type `RESERVATION`, `ADMISSION`,
  Claim, `CONSUMPTION` ou `ReadIntent`.
- **Étage** `OwnRecordStage` et enregistrements propres **attendus** :

| Étage | Enregistrements attendus de la campagne courante |
|---|---|
| `NO_OWN_RECORDS` | aucun |
| `RESERVED` | `RESERVATION` |
| `ADMITTED` | + `ADMISSION` |
| `CLAIMED` | + Claim |
| `CONSUMED` | + `CONSUMPTION` |

- **Absorption.** Lors de la partition des enregistrements propres (`partition_own_records`, avant la classification),
  un enregistrement propre attendu est **absorbé** (exclu de `E`, de F1 et F2, du test de rival, des digests et de
  `inventory_id`) uniquement s'il est **unique pour son type** (tous statuts confondus : un second enregistrement du
  type, même `UNRESOLVED`, empêche toute absorption), `RESOLVED`,
  porte le `campaign_id` courant et, pour `RESERVATION`, `ADMISSION`, Claim et `CONSUMPTION`, une fenêtre **égale à
  `W`**. L'absorption ne vérifie que la forme : l'identité des enregistrements (hash, chaîne) reste à E3-D et E3-J.
  Le Claim E1 ne porte aucune fenêtre propre : la fenêtre du finding `FINAL_HOLDOUT_CLAIM` est celle de la fenêtre
  `FINAL_HOLDOUT` du plan désigné par `split_plan_id` du Claim, fournie par l'appelant (E3-B) ; si elle est introuvable,
  le finding est `UNRESOLVED` (cause `WINDOW_UNKNOWN`) et la classe est `UNDETERMINED`, jamais `FRESH` (sous réserve
  de R1 : une exposition établie par ailleurs l'emporte).
- **Échec fermé.** Un enregistrement propre non absorbé (doublon, fenêtre différente, type inattendu) ou un
  enregistrement attendu absent (noté `missing:<TYPE>`) n'est **jamais** masqué : s'il est exposant (`CONSUMPTION`,
  Claim, `ReadIntent`), c'est une **exposition établie** (`RETROSPECTIVE_EXPOSED`, par échec fermé et quel que soit
  son verdict de recouvrement : un exposant propre non absorbé et `RESOLVED` est traité comme `OVERLAPS`, cas
  particulier de R1 amendant 23.28) ; un exposant propre `UNRESOLVED` (par exemple un Claim de fenêtre `WINDOW_UNKNOWN`)
  suit R2 et donne `UNDETERMINED` si aucune exposition établie n'existe par ailleurs ; s'il est non exposant
  (`RESERVATION`, `ADMISSION`) ou absent, c'est une anomalie qui donne `UNDETERMINED` (code
  `OWN_REGISTRATION_ANOMALY`, jamais traité comme rival). Un Claim dupliqué par copie de dossier donne donc
  `RETROSPECTIVE_EXPOSED`. Une exposition étrangère n'est jamais masquée. Les identifiants d'anomalie propre sont les
  ids des enregistrements propres **non absorbés et non exposants** (les exposants non absorbés figurent dans les
  identifiants d'exposition établie ou non résolus), plus `missing:<TYPE>` pour chaque type attendu dont il n'existe
  **aucun** enregistrement (un type présent en doublon n'est jamais « manquant »). Codes de raison : un exposant propre
  établi donne `EXPOSURE_ESTABLISHED_INVENTORY` (F1 `NOT_MET`) ; un exposant propre `UNRESOLVED` donne
  `UNRESOLVED_SOURCE` (F1 `UNVERIFIED`) ; `OWN_REGISTRATION_ANOMALY` (et son jumeau F1) est réservé aux enregistrements
  propres **non exposants** non absorbés ou manquants. Les autres types exposants portant le `campaign_id` courant
  (`HOLDOUT_ACCESS_EVENT`, `VALIDATION_RUN_OOS`, `JOB_EXECUTION`, `V1_CAMPAIGN_OOS`) ne sont jamais absorbés : ce sont
  des expositions ordinaires.
- **Identité d'un finding.** L'identifiant d'un finding inclut son localisateur (ou son occurrence ; pour un
  enregistrement du registre, son `seq` ou son hash, jamais le `campaign_dir_locator`, hors identité) : deux copies de
  contenu identique, y compris sous deux dossiers, restent **deux findings distincts** et ne sont jamais fusionnées ou
  dédupliquées. Un identifiant de finding dupliqué dans un inventaire lève `ValueError` (échec fermé). Un test E3-B
  « deux copies d'un même Claim » est obligatoire.
- **Étage vérifié.** L'étage n'est **jamais une simple affirmation de l'appelant**, dans aucun mode (`SYNTHETIC` comme
  `REAL`) : E3-D et E3-J le dérivent des artefacts persistés (chaîne du registre, Claim, `ReadIntent`) et le refusent
  s'il est incompatible avec eux (test E3-J obligatoire de cette dérivation). E3-A, module pur, reçoit l'étage et le vérifie contre l'inventaire (comptes exacts, échec fermé) : un étage trop
  bas ou trop haut produit une anomalie ou une exposition, jamais une classe `FRESH`.
- **Aucune autorité d'admission.** La classification pure d'E3-A **n'est jamais une autorité** : un tuple de refus
  vide ne vaut pas autorisation. Une classification calculée à l'étage `CLAIMED` ou `CONSUMED` ne peut en aucun cas
  servir à publier ou republier une `ADMISSION`, ni à acquérir un nouveau Claim. L'unicité par campagne (23.10) et E2
  restent les seules autorités ; après une `CONSUMPTION`, aucun second accès n'est possible. Aux étages
  `ADMITTED` à `CONSUMED`, la classification ne sert qu'à l'audit et aux revérifications de 23.27.3.

#### 23.27.3 — Identités de l'inventaire et attestation (A4)

Trois identités distinctes, aucune ne remplace l'autre :
- `inventory_id` : identité **scientifique** de classification, stable ; SHA-256 canonique de la version, de la
  fenêtre `W`, de `complete`, de `scanned_roots` et des findings **non absorbés**. Elle n'inclut ni `trial_accounting`, ni
  l'étage, ni horodatage, ni les plans informatifs. `scanned_roots` ne contient que les **racines d'audit statiques**
  du fichier de configuration de root (triées, dédupliquées) ; les dossiers de campagnes découverts par la chaîne du
  registre sont des sources **dérivées** lues, jamais des racines : ils n'entrent dans `inventory_id` que par les
  findings qu'ils portent. Une `RESERVATION` étrangère non recoupante, même avec un nouveau
  `campaign_dir_locator`, ne modifie donc pas `inventory_id`.
- `inventory_content_digest` : SHA-256 canonique de `{inventory_id, trial_accounting}` (sans horloge) ; il intègre les
  compteurs.
- `inventory_content_hash` : hash du contenu **intégral persisté** du A0 (E3-B), `created_at` inclus. Le A0 persisté
  contient `inventory_id`, `inventory_content_digest`, `trial_accounting`, le contexte propre
  (`campaign_id` courant et étage) et `created_at`.

L'**attestation** épingle obligatoirement `inventory_content_hash` (donc le contenu complet) **et** `inventory_id`.
**Avant l'admission** (étapes 8 à 11 de 23.17), E3-J recharge le A0 persisté (son `content_hash` doit égaler celui
attesté), recalcule un A0′ à neuf et exige l'égalité de `inventory_id`, de `static_sources_digest`, de la projection de
recouvrement **et** de `inventory_content_digest`. Une modification des compteurs de `trial_accounting` après
l'attestation invalide donc l'attestation (refus `ACCOUNTING_CHANGED`), **même si la classification scientifique est
inchangée**.

**Après le Claim et la `CONSUMPTION`**, le contrôle de l'étape 13 de 23.17
compare `inventory_id`, `static_sources_digest` et la projection (en plus des revérifications de 23.17 sur la tête
des déclarations et l'autorisation) ; il **ne compare jamais la comptabilité**. Un compteur d'une autre campagne ne peut
jamais annuler une exécution après un droit consommé. Une exposition étrangère nouvelle (par exemple une `CONSUMPTION`
étrangère non recoupante) modifie `inventory_id` et peut en revanche annuler l'exécution : c'est un changement
scientifique, accepté (23.17 étape 13, inchangé).

**Reprise après crash entre l'`ADMISSION` durable et le Claim** (23.10, « Crash avant le Claim » : « rejoue les
vérifications » s'entend sans la comptabilité) : la comptabilité n'est ni recalculée ni comparée ; seuls
`inventory_id`, `static_sources_digest` et la projection sont revérifiés (la `RESERVATION` n'a pas d'`inventory_id` ;
l'étape 8 de la publication ne compare que `static_sources_digest` et la projection). Dans 23.10 et 23.17,
« attestation valide » ou « non périmée » après l'`ADMISSION` durable s'entend **hors comptabilité**. `ACCOUNTING_CHANGED` n'existe donc qu'**avant la publication de l'`ADMISSION`** (contrôles 1 à 7 de
23.27.4) ; une fois l'`ADMISSION` durable, aucun compteur ne peut brûler la fenêtre. La comptabilité finale est
recalculée par E3-B pour le `ClosingRecord` (23.27.5).

#### 23.27.4 — Péremption de l'attestation et publication de l'`ADMISSION` (A2, A2 bis)

**Remplace la dernière phrase de « Instant de péremption de l'inventaire » (23.10).** L'attestation est périmée dès que :
une source non registre change ; une réservation ou une admission d'une autre campagne dont la fenêtre recoupe (ou est
illisible) apparaît ; une **exposition d'une autre campagne, dont une `CONSUMPTION`, apparaît dans `E` même sans
recouvrement** avec `W` (elle modifie `inventory_id`) ; la **comptabilité des essais change**, y compris par la
création d'une `RESERVATION` d'une campagne nouvellement comptée (elle modifie `campaigns` sans changer la classe
scientifique) ou la clôture d'une autre campagne ; le préfixe épinglé n'est plus un préfixe de la chaîne ; la tête des
déclarations change ; la version de la classification change. Une `ADMISSION` ou un `REBIND` d'une campagne **déjà
comptée** est neutre (hors recouvrement avec `W`). Une `CONSUMPTION` étrangère **n'est pas neutre**.

**Contrôles préalables à la publication d'une `ADMISSION`** (étape 2 de 23.10, **répétés après tout conflit de slot**) :
1. `inventory_id` ;
2. `inventory_content_digest` ;
3. `static_sources_digest` ;
4. la projection de recouvrement ;
5. les déclarations (tête inchangée) et l'attestation (classification recalculée égale) ;
6. l'autorisation ;
7. le préfixe de chaîne épinglé.

La péremption par changement de comptabilité ne vaut que **jusqu'à la publication de l'`ADMISSION`** (23.27.3) ; les
autres causes de la liste restent valables ensuite dans la mesure où 23.17 les revérifie.

**Une modification concurrente détectée avant la publication n'est jamais ignorée** : l'attestation est périmée, arrêt,
nouvelle attestation et nouvelle autorisation humaines. Il n'existe aucune nouvelle tentative automatique qui poursuit
sur une attestation périmée : après un conflit de slot (23.10, étape 5), une nouvelle tentative n'est permise que si
les sept contrôles sont **inchangés**. La `RESERVATION` n'a pas d'attestation : ses contrôles (23.10) sont inchangés.

#### 23.27.5 — Comptabilité des essais (A6)

- Les compteurs portent sur des **campagnes distinctes**, sans double compter les trois types d'enregistrement d'une
  même campagne : `campaigns` = nombre de `campaign_id` distincts parmi les `RESERVATION`, `ADMISSION` et
  `CONSUMPTION` de la chaîne ; `abandoned_reservations` = parmi eux, ceux sans `ClosingRecord` terminal (introuvable ⇒
  abandonnée, conservateur) ; `research_runs` et `strategies` sont comptés sur ces campagnes, sur les campagnes V1
  avec OOS et sur les nombres déclarés (23.11 d'origine, inchangé) ; `failed_ingestion_attempts` et
  `void_commitments` sont comptés **sans** restriction aux campagnes de la chaîne (précision : 23.11 d'origine ne les
  restreignait pas), y compris les tentatives et engagements nuls antérieurs à toute `RESERVATION`.
- La comptabilité du **A0 avant admission exclut la campagne courante**. Le **`ClosingRecord` conserve la comptabilité
  finale incluant cette campagne** (`campaigns` augmenté de un, à état par ailleurs inchangé).
- **Responsabilités.** E3-A : modèle pur `TrialAccounting`, calcul de `inventory_content_digest`. E3-B : calcul des
  compteurs, persistance du A0, relecture stricte. E3-J : revérification avant l'admission (23.27.3), jamais après le
  Claim.
- Comptabilité **non décisionnelle pour la classe** (elle périme toutefois l'attestation avant l'admission, 23.27.3) :
  elle n'entre ni dans la classe ni dans `inventory_id`, aucune correction de
  multiple testing et aucun seuil ne sont introduits. Le calcul de `abandoned_reservations` n'est pas atomique avec la
  publication (un `ClosingRecord` est hors registre) : ce risque est accepté. Coût de disponibilité accepté : une
  nouvelle campagne d'un tiers ou une clôture périme une attestation avant l'admission.

#### 23.27.6 — Contrat d'identité entre étages

En l'absence d'élément **étranger** nouveau, `inventory_id`, `static_sources_digest`, la projection de recouvrement,
`input_digest` et `classification_id` sont **identiques** aux étages `RESERVED`, `ADMITTED`, `CLAIMED` et `CONSUMED`.
Seul le champ d'audit `absorbed_own_record_ids` diffère, et il est exclu de `classification_id`. Exception : un
enregistrement propre non absorbable (`UNRESOLVED`, doublon, fenêtre ≠ `W`) est un finding non absorbé ; il entre dans
`inventory_id`, qui peut alors différer d'un étage à l'autre (échec fermé, détecté comme changement d'exposition à
l'étape 13 de 23.17). Sont exclus de toute
identité sémantique : l'étage, les enregistrements absorbés, `trial_accounting` (présent seulement dans
`inventory_content_digest`), les plans informatifs et tout horodatage ; le contenu d'audit horodaté
(`inventory_content_hash`) est distinct. Les déclarations référencent l'`inventory_id` calculé sur les findings non
absorbés ; une déclaration qui référence un autre `inventory_id` est refusée. Si l'une de ces stabilités se révélait
impossible, ce serait un BLOCKER à signaler ; aucun nouveau contrat ne doit être improvisé.

#### 23.27.7 — Périmètres des slices précisés

- **E3-A** : calcul **pur** (types, invariants, classification, identités, `t_sel` effectif, refus de classification) ;
  bibliothèque standard seulement ; aucune E/S, horloge, moteur, E1/E2.
- **E3-B** : construction et lecture stricte de l'inventaire, persistance du A0 et de ses hashs, calcul de la
  comptabilité, persistance des déclarations, primitive publique de recouvrement d'intervalles.
- **E3-C/D** : stockage durable, registre, admissions.
- **E3-E** : engagement, preuves de temps, modèles d'attestation et d'autorisation.
- **E3-J** : vérification des étages réels (dérivation depuis les artefacts persistés), reclassification, admission.
  E3-J refuse de traiter une classification d'étage `ADMITTED` ou supérieur comme une autorisation de publier une
  `ADMISSION` ou d'acquérir un Claim (test E3-J obligatoire) ; E3-A ne l'impose pas, étant pur.
Aucune nouvelle abstraction générale n'est introduite.

### 23.28 — Contrat de référence de la classification E3-A (spécifié, non implémenté)

Module prévu `gate_v_final_holdout_protocol.py`, tests `tests/test_gate_v_final_holdout_protocol.py`. Dépendances :
bibliothèque standard seulement. Conventions d'E1 : `type(x) is str` strict, `ValueError` pour une valeur invalide,
`TypeError` pour une erreur d'appel, `_canonical_json` dupliqué (Décision 20.3). Instants : chaîne UTC à fraction fixe de
six chiffres (`YYYY-MM-DDTHH:MM:SS.ffffffZ`), comparaisons sur `datetime` parsé.

**Classes et niveaux.** Trois classes (`FRESH_UNEXPOSED_DECLARED`, `RETROSPECTIVE_EXPOSED`, `UNDETERMINED`) et trois
niveaux (`PROSPECTIVE_ANCHORED`, `UNSEEN_HISTORICAL`, `NOT_APPLICABLE`).
- **Précédence** : R1 une exposition établie (exposante, `RESOLVED`, `OVERLAPS`, inventaire ou déclarée, après
  absorption ; plus tout exposant propre `RESOLVED` non absorbé, 23.27.2) donne `RETROSPECTIVE_EXPOSED` ; R2 sinon, un finding non résolu, un inventaire incomplet ou une anomalie
  propre donne `UNDETERMINED` ; R3 sinon `FRESH_UNEXPOSED_DECLARED`. L'exposition établie l'emporte sur toute source
  `UNDETERMINED`.
- **Au moins une déclaration** est exigée pour classifier (`ValueError` sinon) : la classe n'existe qu'après l'étape 2 de
  23.11. Les déclarations ne peuvent que durcir (la sévérité `FRESH` < `UNDETERMINED` < `RETROSPECTIVE_EXPOSED` ne
  baisse jamais quand on en ajoute), et `t_sel` effectif = maximum, jamais avancé dans le passé.
- **Niveau** : `RETROSPECTIVE_EXPOSED` donne `NOT_APPLICABLE` ; six conditions `MET` donnent `PROSPECTIVE_ANCHORED` ;
  sinon `UNSEEN_HISTORICAL` (y compris pour `UNDETERMINED`, lecture littérale de 23.3).
- **Éligibilité distincte** : `admission_refusals` renvoie, dans l'ordre, un refus de classe (`CLASS_RETROSPECTIVE_EXPOSED`
  ou `CLASS_UNDETERMINED`), sinon `LEVEL_NOT_PROSPECTIVE_ANCHORED`, puis éventuellement `OVERLAPPING_REGISTRATION`. Un
  tuple vide n'est jamais une autorisation.

**Conditions F1 à F6** (tri-état `MET`/`NOT_MET`/`UNVERIFIED` ; statut = sévérité maximale, `NOT_MET` > `UNVERIFIED` >
`MET` ; une violation connue prime sur une donnée manquante ; toutes les raisons applicables sont cumulées) :

| Condition | `NOT_MET` | `UNVERIFIED` |
|---|---|---|
| F1 | exposition établie | source non résolue, inventaire incomplet ou anomalie propre |
| F2 | fin d'une exposante > `ws`, `t_sel` effectif > `ws` ou > `t_anchor` | exposante non résolue, `t_sel` absent, ancrage inconnu |
| F3 | `max(time)` de S0 ≥ `ws` | `max(time)` absent |
| F4 | réservation non durable ; preuve invalide ; preuve valide d'une autre réservation ; borne > `ws` ou borne + marge > `ws` | réservation inconnue ; preuve absente ou non vérifiable ; marge absente ou ≤ 0 |
| F5 | ingestion ≤ `we` ; plage ≠ engagée | ingestion ou plage inconnue |
| F6 | `hash_linked` faux | — |

`t_anchor` n'est la borne de la preuve que si elle est `VALID` et vise sa propre réservation. `ws` = max accepté en F2.

**Types (décompte).**
- **11 énumérations** : `ExposureClass`, `ChronologyLevel`, `OverlapVerdict`, `SourceStatus`, `SourceKind` (12 valeurs : 8
  exposantes `HOLDOUT_ACCESS_EVENT`, `VALIDATION_RUN_OOS`, `JOB_EXECUTION`, `V1_CAMPAIGN_OOS`, `FINAL_HOLDOUT_CLAIM`,
  `CONSUMPTION`, `READ_INTENT`, `DECLARED_UNRECORDED_WORK` ; 2 non exposantes `REGISTRY_RESERVATION`,
  `REGISTRY_ADMISSION` ; 2 de capacité inconnue `UNKNOWN_SOURCE`, `REGISTRY_UNREADABLE`, jamais `RESOLVED`),
  `UnresolvedCause` (7), `ConditionStatus`, `TimeProofStatus`, `ReasonCode` (**32** : 7 de niveau classe dont
  `OVERLAPPING_REGISTRATION` et `OWN_REGISTRATION_ANOMALY`, et 25 codes F1 à F6), `AdmissionRefusal` (**4**),
  `OwnRecordStage` (5).
- **11 dataclasses immuables** : `ExposureFinding` (10 champs), `TrialAccounting` (6), `ExposureInventory` (7),
  `ExposureDeclaration` (8), `DeclarationSet` (2), `TimeProofFact` (3), `ChronologyFacts` (7), `OwnCampaignContext` (2),
  `ClassificationInput` (4), `FConditionResult` (3), `ExposureClassificationResult` (16).
- **16 fonctions publiques** : `normalize_utc_instant` ; `build_exposure_finding`, `build_exposure_inventory`,
  `build_exposure_declaration`, `build_chronology_facts` ; `partition_own_records` ; `compute_exposure_inventory_id`,
  `compute_inventory_content_digest`, `compute_declaration_id`, `compute_classification_input_digest`,
  `compute_static_sources_digest`, `compute_overlap_projection_hash`, `compute_effective_t_sel` ; `classify_exposure`,
  `admission_refusals`, `classification_result_to_record`.
- **Interface publique.** Les noms et l'ordre des champs des dataclasses (autres que `TrialAccounting`, nommé
  ci-dessous) constituent l'interface publique proposée à l'approbation de l'utilisateur **avant** le premier test TDD
  d'E3-A ; ils ne sont pas figés par la présente ADR, qui fixe les décomptes, les valeurs d'énumérations nommées
  ci-dessous et les comportements. Valeurs : `OverlapVerdict` `OVERLAPS`, `NO_OVERLAP`, `UNKNOWN` ; `SourceStatus`
  `RESOLVED`, `UNRESOLVED` ; `ConditionStatus` `MET`, `NOT_MET`, `UNVERIFIED` ; `TimeProofStatus` `VALID`, `INVALID`,
  `UNVERIFIABLE`, `ABSENT` ; `OwnRecordStage` `NO_OWN_RECORDS`, `RESERVED`, `ADMITTED`, `CLAIMED`, `CONSUMED`.
- **Valeurs nommées.** `UnresolvedCause` : `UNREADABLE`, `INVALID_SCHEMA`, `UNKNOWN_SCHEMA_VERSION`,
  `WINDOW_UNKNOWN`, `TIMEZONE_UNKNOWN`, `PLAN_UNRESOLVED`, `UNKNOWN_SOURCE_TYPE`. `TrialAccounting` :
  `research_runs`, `strategies`, `campaigns`, `abandoned_reservations`, `failed_ingestion_attempts`,
  `void_commitments`. `ReasonCode` de niveau classe (7) : `EXPOSURE_ESTABLISHED_INVENTORY`,
  `EXPOSURE_ESTABLISHED_DECLARED`, `UNRESOLVED_SOURCE`, `INVENTORY_INCOMPLETE`, `T_SEL_LOWERING_IGNORED`,
  `OVERLAPPING_REGISTRATION`, `OWN_REGISTRATION_ANOMALY`. `ReasonCode` des conditions (25) : F1 (4)
  `F1_EXPOSURE_ESTABLISHED`, `F1_SOURCES_UNRESOLVED`, `F1_INVENTORY_INCOMPLETE`, `F1_OWN_ANOMALY` ; F2 (6)
  `F2_EXPOSURE_WINDOW_UNKNOWN`, `F2_T_SEL_MISSING`, `F2_ANCHOR_UNKNOWN`, `F2_EXPOSURE_AFTER_WS`, `F2_T_SEL_AFTER_WS`,
  `F2_T_SEL_AFTER_ANCHOR` ; F3 (2) `F3_S0_MAX_TIME_MISSING`, `F3_S0_NOT_BEFORE_WINDOW` ; F4 (9)
  `F4_RESERVATION_UNKNOWN`, `F4_RESERVATION_NOT_DURABLE`, `F4_PROOF_ABSENT`, `F4_PROOF_UNVERIFIABLE`,
  `F4_PROOF_INVALID`, `F4_PROOF_NOT_OWN_RESERVATION`, `F4_MARGIN_MISSING`, `F4_MARGIN_NOT_POSITIVE`,
  `F4_ANCHORED_TOO_LATE` ; F5 (3) `F5_INGESTION_MISSING`, `F5_INGESTED_BEFORE_WINDOW_END`, `F5_RANGE_MISMATCH` ; F6 (1)
  `F6_HASH_LINK_BROKEN`. Le tri des raisons suit l'ordre de déclaration de cette énumération.

**Invariants clés.** `RESOLVED` exige un recouvrement connu, une fenêtre complète (début < fin) et un `content_hash`
hexadécimal de 64 caractères (sauf `DECLARED_UNRECORDED_WORK`, où il vaut `None`) ; `UNRESOLVED` exige `UNKNOWN` et une
cause ; la validité du verdict de recouvrement est contrôlée par une formule privée (`a.start < b.end ∧ b.start <
a.end`) pour les findings de l'inventaire **et** les expositions déclarées ; les `RESERVATION` et `ADMISSION`
`RESOLVED` d'autres campagnes doivent recouper `W` (les autres ne sont pas listées : elles ne figurent que dans
`trial_accounting`) ; `DECLARED_UNRECORDED_WORK` est interdit dans l'inventaire ; les préfixes `declared:` (ids
déclarés, `declared:<seq sur 4 chiffres>:<position sur 4 chiffres>`) et `missing:` sont réservés ; le `snapshot_id` est
informatif et n'est jamais lu par la décision ; les déclarations forment une chaîne dense de `declaration_id` sans
horloge et référencent l'`inventory_id` courant ; la marge d'ancrage est un fait fourni (jamais un défaut).

**Identités** (SHA-256 du JSON canonique, sans horodatage) : `inventory_id` (23.27.3) ; `inventory_content_digest` ;
`compute_declaration_id` (version, `seq`, déclarant, `inventory_id`, `prev_declaration_id`, `t_sel` déclaré,
expositions déclarées complètes, comptes déclarés) ; `input_digest` (version des règles, `inventory_id`,
`campaign_id` courant, déclarations complètes, `hash_linked`, chronologie complète ; **sans** étage ni enregistrements
absorbés) ; `classification_id` (version des règles, `input_digest`, classe, niveau, `t_sel` effectif, seqs ignorés,
identifiants établis, non résolus, chevauchants et d'anomalies propres, conditions, raisons ; **sans**
`absorbed_own_record_ids`). `static_sources_digest` et la projection de recouvrement portent sur les findings non
absorbés. Liste canonique vide : SHA-256 de `[]` = `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`.

**Obligations de test E3-A** (synthétiques ; les constantes ne sont jamais des valeurs de policy). Scénario de base
B0 : `W = [2026-11-02T00:00:00.000000Z, 2026-12-01T00:00:00.000000Z)` (`ws` = 2026-11-02, `we` = 2026-12-01), campagne
courante `campaign_a` à l'étage `RESERVED` avec sa propre réservation de fenêtre `W`, inventaire complet sans autre
finding, une déclaration sans exposition, chronologie entièrement valide : `t_sel` effectif = 2026-10-20, `t_anchor` =
2026-10-25 (preuve `VALID` de sa propre réservation durable), marge = 1 jour (borne + marge = 2026-10-26 ≤ `ws`),
`max(time)` de S0 = 2026-05-19T12:48:00.000000Z, ingestion de S_H = 2026-12-02, plage engagée, `hash_linked` vrai.
Sortie B0 : `FRESH_UNEXPOSED_DECLARED`, `PROSPECTIVE_ANCHORED`, aucune
raison, F1 à F6 `MET`, aucun refus, réservation propre absorbée.

| Variation de B0 | Sortie attendue |
|---|---|
| exposition `OVERLAPS` établie (inventaire ou déclarée) | `RETROSPECTIVE_EXPOSED`, `NOT_APPLICABLE`, F1 `NOT_MET` |
| exposition établie + source non résolue | `RETROSPECTIVE_EXPOSED` (l'exposition l'emporte) |
| source non résolue seule ; inventaire incomplet | `UNDETERMINED`, `UNSEEN_HISTORICAL`, F1 `UNVERIFIED` |
| inventaire sans déclaration | `ValueError` à la construction de `ClassificationInput` |
| `complete = True` sans `scanned_roots` | `ValueError` |
| réservation d'une autre campagne recoupant `W` (entrée de test directe : une chaîne saine n'en contient jamais, invariant de 23.10) | `FRESH`, `PROSPECTIVE_ANCHORED`, raison et refus `OVERLAPPING_REGISTRATION` |
| réservation ou admission étrangère non recoupante listée | `ValueError` (non listable) |
| sa propre réservation à l'étage `RESERVED` | absorbée : sortie B0, aucun refus |
| deux réservations propres (ids des deux en anomalie, pas de `missing:`) ; réservation propre absente (`missing:RESERVATION`) ; admission propre à l'étage `RESERVED` (id en anomalie) | `UNDETERMINED`, `OWN_REGISTRATION_ANOMALY`, F1 `UNVERIFIED` |
| `CONSUMPTION` propre à l'étage `RESERVED` ; seconde `CONSUMPTION` propre à l'étage `CONSUMED` ; Claim propre dupliqué | `RETROSPECTIVE_EXPOSED` |
| Claim propre attendu (étage `CLAIMED`) mais `UNRESOLVED` (`WINDOW_UNKNOWN`), sans autre exposition | `UNDETERMINED`, raison `UNRESOLVED_SOURCE`, F1 `UNVERIFIED` (pas d'`OWN_REGISTRATION_ANOMALY`) |
| même cas avec une exposition étrangère établie | `RETROSPECTIVE_EXPOSED` |
| deux findings de même identifiant dans un inventaire | `ValueError` |
| étage `CONSUMED` avec les quatre enregistrements propres | sortie B0 ; F2 `MET` ; mêmes `inventory_id`, digests, projection, `input_digest` et `classification_id` qu'à l'étage `RESERVED` ; seul `absorbed_own_record_ids` diffère |
| étage reçu trop bas (enregistrement propre non attendu présent) : exposant (Claim, `CONSUMPTION`, `ReadIntent`) ; non exposant (`ADMISSION`) | `RETROSPECTIVE_EXPOSED` ; `UNDETERMINED` (`OWN_REGISTRATION_ANOMALY`) |
| étage reçu trop haut (enregistrement attendu absent) | `UNDETERMINED`, `OWN_REGISTRATION_ANOMALY`, id `missing:<TYPE>` |
| réservation propre de fenêtre ≠ `W` | anomalie, `UNDETERMINED` |
| `campaign_id` absent sur un enregistrement `RESOLVED` des cinq types ; `campaign_id` courant vide ; id d'inventaire préfixé `missing:` ou `declared:` | `ValueError` |
| `t_sel` effectif repoussé jusqu'à `t_anchor` inclus ; repoussé après `t_anchor` mais ≤ `ws` ; repoussé après `ws` ; abaissé par une déclaration ultérieure ; absent à l'engagement | F2 `MET` ; F2 `NOT_MET` (`F2_T_SEL_AFTER_ANCHOR`) ; F2 `NOT_MET` (`F2_T_SEL_AFTER_WS` et `F2_T_SEL_AFTER_ANCHOR`) ; effectif inchangé, `seq` ignoré listé, raison `T_SEL_LOWERING_IGNORED` ; F2 `UNVERIFIED` |
| preuve de temps valide, absente, invalide, non vérifiable, d'une autre réservation | F4 `MET` ; `UNVERIFIED` ; `NOT_MET` ; `UNVERIFIED` ; `NOT_MET` |
| borne + marge = `ws` ; > `ws` ; marge absente ; marge nulle ; borne > `ws` sans marge | F4 `MET` ; `NOT_MET` ; `UNVERIFIED` ; `UNVERIFIED` ; `NOT_MET` |
| `max(time)` de S0 absent, = `ws`, juste avant `ws` | F3 `UNVERIFIED`, `NOT_MET`, `MET` |
| ingestion = `we`, > `we`, plage fausse, absente | F5 `NOT_MET`, `MET`, `NOT_MET`, `UNVERIFIED` |
| `hash_linked` faux | F6 `NOT_MET`, niveau `UNSEEN_HISTORICAL` |
| même exposition sous deux `snapshot_id` | même classe, `inventory_id` différent |
| verdict de recouvrement contredisant les fenêtres | `ValueError` |
| chacun des six compteurs de `trial_accounting` modifié | `inventory_content_digest` change ; `inventory_id`, classe et `classification_id` inchangés |
| `CONSUMPTION` étrangère non recoupante listée | `inventory_id` change (attestation périmée), classe inchangée |
| code de classe `UNRESOLVED_SOURCE`, `INVENTORY_INCOMPLETE`, `OWN_REGISTRATION_ANOMALY` | présent si et seulement si le code F1 jumeau est présent |
| déterminisme, immuabilité, ordre des findings permuté via le builder | mêmes sorties et mêmes identités |
| pureté (test AST), vecteurs de hash littéraux calculés hors du code testé | imports ⊆ bibliothèque standard ; aucune E/S, horloge ni accès marché |
| propriété de monotonie : `D ⊆ D'` | sévérité de classe non décroissante, `t_sel` effectif non décroissant |

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
- **Mise à jour (2026-10-11, additive, ne remplace rien de ce qui précède)** — état réel des tranches :
  - **Slices D1–D6 = INTEGRATED** dans `master` (commits `49ce253` D1, `bbb8aea` D2, `57878c8` D3, `2eeade4` D4,
    `79941df` D5, `86b6473` D6). La mention « `Slice D` = SPEC LOCKED, NOT IMPLEMENTED » de la mise à jour du
    2026-10-06 décrit l'état à cette date.
  - **Slice E1 = IMPLEMENTED + TESTED localement, NON COMMITTED** : `gate_v_final_holdout_claim.py` et
    `tests/test_gate_v_final_holdout_claim.py` (146 tests dédiés ; suite complète 3582/3582 mesurée localement
    le 2026-10-11). Aucun Claim n'a été créé ni persisté.
  - **Slice E2 = SPECIFIED (Décision 22), NOT IMPLEMENTED** ; **Slice E3 = DESIGN NOT LOCKED**, conditionnée
    par le contrôle d'exposition de 22.2 et les obligations de 22.12.
  - **La Décision 22 précise les Décisions 9, 10, 11, 13, 20 et 21 sans en modifier aucune formule.** L'unicité
    du Claim est **par campagne** ; elle ne démontre **pas** la fraîcheur du `FINAL_HOLDOUT`, et l'absence de
    `HoldoutAccessEvent` n'en est jamais la preuve.
  - `AF-V-07` = IN PROGRESS, `AF-V-08` = DONE, `GATE V` NON PASSÉE, `FINAL_HOLDOUT` NON ACCÉDÉ pour `AF-V-07`
    (un accès antérieur et distinct est documenté dans `DOMAIN_MODEL.md` §12 pour le plan IG demo d'AF-V-01).
- **Mise à jour (2026-10-12, additive, ne remplace rien de ce qui précède)** — état réel des tranches :
  - **E1 = PUBLIÉ** (commit `707ec51b7edc52e5b5d8c4b040d9454f83b27e45`) et **E2 = PUBLIÉ** (commit
    `9c2bf7ef5ccf692e9d89db7b0ca61038bbd962e4`) dans `origin/master` ; les mentions « E1 NON COMMITTED » et
    « E2 SPECIFIED, NOT IMPLEMENTED » de la mise à jour du 2026-10-11 décrivent l'état à cette date. Tests E2
    rapportés précédemment : 3772 réussis, 2 ignorés (non rejoués pour cette mise à jour documentaire).
  - **E3 = conception formalisée par la Décision 23, en cours de validation documentaire, NON IMPLÉMENTÉE** ; la
    mention « E3 = DESIGN NOT LOCKED » du 2026-10-11 décrit l'état à cette date. Le mode `REAL` est
    **désactivé et non qualifié** ; aucune qualification d'infrastructure n'est affirmée.
  - Aucun accès `FINAL_HOLDOUT` nouveau, aucun Claim réel. `AF-V-07` = IN PROGRESS, `GATE V` NON PASSÉE, aucun
    Champion qualifié.
- **Mise à jour (2026-10-13, additive, ne remplace rien de ce qui précède)** : l'**addendum E3-A** (23.27 et 23.28,
  avec notes de renvoi dans 23.3, 23.6, 23.10, 23.11, 23.17 et 23.26) aligne la Décision 23 sur le design E3-A :
  expositions propres par `campaign_id` et par étage vérifié, comptabilité des essais hors de `inventory_id` mais dans
  `inventory_content_digest`, péremption de l'attestation précisée. **E3-A = design verrouillé sous réserve de la revue
  de cet addendum, NON IMPLÉMENTÉ.** Le mode `REAL` reste **désactivé et non qualifié**. Aucun accès `FINAL_HOLDOUT`
  nouveau, aucun Claim réel. `AF-V-07` = IN PROGRESS, `GATE V` NON PASSÉE, aucun Champion qualifié.
