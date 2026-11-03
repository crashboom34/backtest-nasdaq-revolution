# E3-E — K1 Étape 2, N-VIDE-2 : protocole d'audit obligatoire (B3 v6 + L3-A + rescan) — note de CONCEPTION ; N2-a IMPLÉMENTÉ ET TESTÉ LOCALEMENT, le reste PROPOSED

**Statut (2026-11-03, mis à jour après N2-a).** La tranche **N2-a seule** (noyau : requête, S1, recevabilité, L3-A par racine, diagnostic des répertoires vides, projections F / I, S2, rapport) est **approuvée dans son principe et implémentée localement** (`gate_v_audit_protocol.py`, non commité, non poussé ; section 19). **Tout le reste de cette note reste PROPOSED** : N2-b, N2-c, D12 / D13 opérationnels, N-VIDE-3, L3-B, E3-J et l'ensemble de D1 à D13 ne sont pas acceptés ; R9 reste PROPOSED globalement. Checkpoint : `1ffa80f422af64bc52e70eef4679030a5af360e3` (= `origin/master`, divergence 0/0). Aucun amendement de l'ADR 0025, de R9, d'E3-A, de B3 (v4 / v5 / v6), de B5 / A0 ni de L3-A n'est opéré par cette note.
`REAL` = DISABLED / NOT QUALIFIED · `GATE V` = NON PASSÉE · `FINAL_HOLDOUT` = NON ACCÉDÉ. Aucune admission, aucun Claim, aucun `SourceKind` nouveau, aucun L3-B, DERIVED, `evidence_hash`, E3-J.

## 1. Sources lues et préchecks

| Source | Ce qui en est retenu (lu, pas supposé) |
|---|---|
| `CLAUDE.md`, `AI_HANDOFF.md` §§80-82 | politique, limites de la publication précédente (§82.6, §82.9), empreintes d'index `1abfc53f…` (`diff --cached --raw --no-abbrev`) et `8b78a333…` (`diff --cached --binary`) reproduites avant cette mission |
| notes L3-A et N-VIDE-1 | obligations futures (L3-A §6), diagnostic A/B/C (N-VIDE-1 §4 bis), frontière N-VIDE-2 / E3-J (§5), risques (§6) |
| `gate_v_exposure_scan.py` (B2) | `scan_audit_roots` : double passe, `max_attempts`, `hooks_used`, `ExposureScan` = dataclass ordinaire **sans jeton de provenance** (constructible à la main) ; `ScanLimits`, `HashLimits`, `ScanHooks` |
| `gate_v_exposure_interpreters*.py` (B3 v4/v5/v6) | `interpret_audit_roots[_v5|_v6]` appellent B2 eux-mêmes (« aucune observation reçue d'un appelant ») ; v6 = v5 + raisons `MANIFEST_*`, même table, même digest |
| `gate_v_k1s2_{verifier,observations,emptiness}.py` (L3-A) | fonctions pures et totales ; `requires_independent_rescan` toujours vrai ; `NOT_PROVEN` ; `observed_tree_from_scan` ne vérifie que le digest de table, `hooks_used`, la racine |
| `gate_v_exposure_inventory.py` (B4), `gate_v_exposure_store.py` (B5/A0) | `assemble_exposure_inventory(interpretation, registry=, accounting=, own_context=)` ; `build/publish/read_exposure_inventory` ; A0 formats 1 et 2 ; `HASHED_RULES_DIGESTS` ; `RulesVersions.is_current()` lié à v4 |
| `gate_v_inventory_preconditions.py` | garde PURE, ne retourne que des refus ; « la garde n'est PAS opérationnelle de bout en bout » |
| `gate_v_campaign_manifest_v2.py` (D2) | producteur : création à la révision 0, +1 par commande, `execution_started` jamais remis à faux ; fichiers `manifest.json`, `technical_failure.json`, `manifest.update.lock` |
| `gate_v_registry_append.py`, `_views.py`, `gate_v_final_holdout_claim_acquisition.py` | aucun écrivain public de RESERVATION / ADMISSION / REBIND ; `publish_consumption` exige une ADMISSION relue ; l'acquisition du Claim ne référence ni inventaire ni B3 |
| ADR 0025 (décisions concernées) | 23.24 (plafonds, valeurs opérationnelles ouvertes), 23.29.6 (double passe), 23.30.1 (trois états de preuve), 23.31 (pins A0) ; design Étage 2 §§5, 7, 10 |

Préchecks de cette mission : branche `master`, HEAD = `origin/master` = `1ffa80f`, divergence 0/0, index réel intact (mêmes deux empreintes), travaux étrangers non touchés (`AGENTS.md` M, ADR 0016 A, `skills-usage.md` M indexés ; `AI_HANDOFF.md`, `CONTEXT.md`, note de design Étage 2, `api/`, `frontend/`, `services/`, etc. non indexés), `app_corrupted_backup.py` non touché, 4,0 Gio libres, aucun téléchargement, aucun backtest.

## 2. Cartographie des appelants réels

Mesure : recherche des imports (`from|import gate_v_exposure_*`, `gate_v_inventory_preconditions`, `gate_v_k1s2_*`) sur tous les `*.py` du dépôt.

| Capacité | API existante | Appelants de **production** | Appelants de test | Composant manquant |
|---|---|---|---|---|
| Scan d'audit | `scan_audit_roots` (B2) | B3 (`interpret_audit_roots*`) seulement | nombreux | — |
| Interprétation B3 v4 / v5 / v6 | `interpret_audit_roots`, `_v5`, `_v6` | v5 appelé par v6 ; v6 **jamais appelé en production** ; B5 ne fait que lire les constantes | tests B3, B5, différentiel | aucun appelant d'audit |
| Construction d'inventaire (B4) | `assemble_exposure_inventory` | **aucun** | tests B4, B5, intégration | aucun producteur de `RegistryView` / `AccountingViews` hors tests (mesuré : ces classes sont définies dans `gate_v_exposure_inventory.py` et instanciées uniquement par des tests) |
| Classification FRESH | E3-A (`gate_v_final_holdout_protocol`) | **aucun appelant d'audit** | tests | — |
| Lecture / persistance A0 | `read_exposure_inventory`, `load_exposure_inventory`, `publish_exposure_inventory` (B5) | `publish_*` : **aucun**. Lecture : **B6** (`gate_v_exposure_declarations.py:871`) charge par `load_exposure_inventory` tout A0 de `exposure/`, **sans contrôle de version** | tests | aucun écrivain d'audit ; aucun contrôle de `rules_versions` à la lecture de production |
| Préconditions RESERVATION / ADMISSION | `inventory_precondition_refusals` | **aucun** | tests | aucun écrivain RESERVATION / ADMISSION (E3-D : « moteur interne, aucune publication exportée ») |
| Vérification de chaîne L3-A | `verify_run_chain`, `diagnose_emptiness`, `observed_tree_from_scan` | **aucun** (test d'absence d'import dans v6) | tests L3-A | adaptateur d'audit (E3-J) |
| Accès FINAL_HOLDOUT | `acquire_…` (E2), `publish_consumption` (E3-D) | `publish_consumption` exige une ADMISSION relue ; l'API web (`api/app.py`, non suivi) déclare `real.final_holdout = disabled` | tests | l'ADMISSION n'est publiable par personne : le Claim n'est pas atteignable de bout en bout |

**Conclusions.** (1) Il n'existe **aucun chemin d'audit de production** : rien à « migrer » ni à casser ; la contrainte N-VIDE-2 se pose avant que les appelants n'existent, ce qui est le moment le moins coûteux. (2) Aucun appelant d'admission actif n'existe et aucun n'est supposé. (3) B4 n'a pas de producteur d'entrées de registre / comptabilité : une obligation d'audit « de bout en bout » dépend d'un adaptateur de lecture du registre qui n'existe pas encore (section 13). (4) `ExposureScan`, `ExposureInventory`, `OwnCampaignContext` sont des dataclasses libres : aucune garde de type ne protège un consommateur contre un objet fabriqué.

**Niveau architectural retenu.** Pas dans B2/B3/B4/E3-A (historiques, verrouillés par leurs tests, `is_current()` = v4 ; les rendre « obligatoires » casserait la lecture historique), ni dans la garde de préconditions (pure : ne peut ni lire le disque ni prouver une provenance). Le point d'imposition est une **couture dédiée entre B3/B4/B5 et le futur écrivain E3-J** : un module profond `gate_v_audit_protocol` (nom proposé) dont l'unique interface publique est « audite cette campagne » et dont l'unique résultat est un `AuditReport` typé. L'imposition est triple : (a) par **signature** (la fonction n'accepte que de la configuration, jamais un scan, un arbre ou une interprétation) ; (b) par **graphe d'imports** verrouillé par test (seul le protocole importe `interpret_audit_roots_v6` et L3-A, hors B5 et tests ; le futur écrivain n'importe que le protocole) ; (c) par **ré-exécution** : le report n'est pas un justificatif au porteur, le futur écrivain relance l'audit lui-même au moment de publier.

## 3. Architecture et frontières de confiance

```
 Configuration de l'opérateur (hors campagne)         Données auditées (NON dignes de confiance)
   AuditRequest : racines, fenêtre W, plafonds          dossiers de campagne, validations/, walk_forward/,
   campagne attendue, registre (N2-b)                   manifest.json, fichiers L2, A0 historiques
              │                                                     │
              ▼                                                     ▼
 ┌──────────────────────── gate_v_audit_protocol (NOUVEAU, seule couture) ─────────────────────────┐
 │  validation de requête → S1 = B3 v6 (B2 double passe) → recevabilité → L3-A par racine →         │
 │  projection des faits F1 → (N2-b : registre strict → B4 → A0 pur) → S2 = rescan → F2 = F1 ? →    │
 │  AuditReport typé (aucun booléen « ok »)                                                          │
 └───────────────┬───────────────────────────────────────────────────────────────┬──────────────────┘
                 ▼ (consomme)                                                    ▼ (rend)
     B2 / B3 v6 / L3-A / B4 / B5 (inchangés)                    AuditReport  ──►  lecture humaine (E3-J relance l'audit : il ne reçoit aucun rapport)
```

**Frontières de confiance.** Digne de confiance : le code du dépôt à un SHA connu, la configuration de l'opérateur, le processus d'audit. **Non digne de confiance** : tout contenu sous les racines (y compris `manifest.json` et les preuves L2 : un fichier cohérent n'est pas une preuve), tout A0 déjà persisté (son champ `b3_interpreters` est une **déclaration**, section 5), tout objet passé par un appelant. Limite assumée : en Python, un code du même processus peut forger un `ExposureScan` ou contourner le protocole ; la protection est de **protocole** (signature, graphe d'imports, ré-exécution par E3-J, isolation de processus pour E3-J), pas cryptographique.

**Interface proposée (petite, profonde).**
- `AuditRequest` (dataclass gelée) : `own_campaign_id` (la campagne auditée), `roots` (tuple de `(label, chemin absolu, layout, may_be_empty, expected_name)` ; `expected_name` est le nom de dossier attendu pour une racine `CAMPAIGN_DIR` — la campagne propre **et** les campagnes dérivées d'une chaîne de registre — construits **par le protocole** en `AuditRoot` / `LayoutRoot` frais à chaque passe), `plan_path` et `split_plan_path` (dérivation de `W`, section 4.1) ou `holdout_window_*` configuré, `limits` (`ScanLimits`), `hash_limits` (`HashLimits`), `protocol_limits` (bornes propres : racines de campagne, vérifications de chaîne, octets conservés), `registry_root` (N2-b), `historical_a0_hashes` (facultatif, lecture seule).
- `audit_campaign_exposure(request) -> AuditReport` : fonction **totale** (une requête hostile donne un rapport refusé, jamais une exception ni un résultat partiel), déterministe hors horloge, **sans écriture**. **Pas de couture privée** (section 18, #5) : le protocole appelle `interpret_audit_roots_v6` par un nom de module ; les tests le remplacent par un faux qui enveloppe le vrai v6 pour provoquer les refus défensifs et les dérives entre S1 et S2.
- `AuditReport` (gelé) : voir section 6 et section 19. Son constructeur est public mais impose des invariants (refus ⇔ motif, aucun statut de couche sur un refus) ; les champs d'autorité sont des propriétés constantes. Il n'est ni sérialisable ni copiable (`__reduce__` lève `TypeError`). Limite assumée : un objet du même processus reste forgeable (`object.__new__`), comme tout objet Python.
- Responsabilités : le protocole **orchestre et confronte** ; il ne réimplémente ni scan, ni interprétation, ni vérification de chaîne, ni identité. Test de la suppression : si on le supprime, la complexité (ordre des appels, confrontation des faits, rescan, refus typés) réapparaît chez chaque futur appelant — il est donc profond.

## 4. Contrat N-VIDE-2

**4.1 Entrées autorisées et provenance.** Autorisé : chemins absolus normalisés de racines configurées par l'opérateur (règles d'`AuditRoot` de B2 : absolu, sans `..`, sans préfixe étendu), fenêtre `W`, plafonds explicites, identifiant de campagne attendu. **Interdit par signature** : `ExposureScan`, `ScanObservation`, `ObservedRunTree`, `SourceInterpretation`, `ExposureInventory`, `OwnCampaignContext`, `RegistryView`, `AccountingViews`, `ScanHooks` (aucun paramètre ne les porte). La fenêtre `W` n'est **pas** un champ du plan V2 (`GateVCampaignPlanV2` ne porte que `split_plan_id`) : elle est la frontière `final_holdout` du `DatasetSplitPlan` référencé par ce `split_plan_id` (`dataset_split.py`). La chaîne de dérivation est donc : plan V2 persisté (`load_gate_v_campaign_plan_v2`, qui exige que l'appelant appelle aussi `validate_…_sources` avant de s'y fier) → split plan persisté (chargeur à confirmer à l'implémentation) → `final_holdout`. La requête porte les chemins de ces deux artefacts ; `W` est celle qu'ils établissent, recoupée avec le registre en N2-b (`WINDOW_MISMATCH`). **Tant que ces chargeurs ne sont pas branchés, `W` n'est qu'une valeur configurée par l'opérateur** : le rapport porte alors `window_provenance = UNVERIFIED` et `window_declared_source = OPERATOR_CONFIGURED` (condition normative de la mission N2-a : une fenêtre configurée mais non revalidée est `UNVERIFIED`, jamais présentée comme établie). Les chargeurs ne sont **pas** dans N2-a : `load_gate_v_campaign_plan_v2` n'est pas fiable sans `validate_…_sources` (pré-enregistrement, ResearchRun, politique, dépôt Git), qu'une requête de deux chemins ne peut pas appeler ; une valeur `SPLIT_PLAN_FINGERPRINT_MATCHED` (nom provisoire) n'existera qu'avec ces chargeurs (recoupement `dataset_split_plan_fingerprint(split_plan) == plan.split_plan_fingerprint` et `split_plan_id`, chargeur `load_dataset_split_plan(path, strict=True)`). Les plafonds ne viennent **jamais** du dossier audité. L'étage des enregistrements propres (`OwnRecordStage`) est **dérivé** du registre relu (E3-A : « en production, E3-D et E3-J le dérivent des artefacts persistés »), jamais fourni.

**4.2 Versions minimales.** Voir section 5 : plancher B3 v6, liste blanche explicite, jamais une comparaison de chaînes.

**4.3 Racines.** Chaque `AuditRoot` doit exister, être un répertoire, non lien, et appartenir à un **ensemble de racines configurées** nommé dans la requête ; pour une racine de disposition `CAMPAIGN_DIR`, le dernier segment du chemin est le `expected_name` déclaré **pour cette racine** (un audit d'exposition scanne aussi des dossiers d'autres campagnes : un seul `campaign_id` global les ferait tous refuser ; v6 traite d'ailleurs le nom par racine) — contrôle déjà fait par `observed_tree_from_scan`, répété par le protocole — et le `manifest.json` doit être celui de cette campagne (`FOREIGN_MANIFEST` / `MANIFEST_RUN_FOREIGN` de L3-A et v6). Une racine dont le résolu change entre S1 et S2 (`st_dev`/`st_ino`) ou dont le nom diffère de `expected_name` est refusée (`ROOT_FOREIGN`) ; « hors configuration » n'est pas un refus de l'interface publique (les racines viennent de la requête) mais un contrôle défensif de la couture privée. Chevauchements, liens, jonctions, noms non portables, collisions de casse : refus structurels de B2, convertis en `SCAN_STRUCTURAL_FAILURE` typé (code `StructuralFailure` conservé).

**4.4 Limites de ressources.** Aucune valeur par défaut, aucune valeur « de production » inventée (la valeur normative de 23.24 reste ouverte). Le protocole exige `ScanLimits` **et** `HashLimits` explicites avant tout accès disque — B3 v5/v6 exigent `hash_limits` pour **tout** appel, même sans racine à table hachée (`HASH_LIMITS_MISSING` au lieu du `TypeError` de B3 ; incohérence interne → `REQUEST_INVALID`) —, calcule `scan_worst_case_read_bytes(limits, hash_limits)` **par groupe de disposition et par passe (S1 puis S2)** et refuse si le total dépasse un budget fixé par la requête (`RESOURCE_BUDGET_EXCEEDED`). Bornes propres au protocole : nombre de racines de campagne, nombre de vérifications de chaîne, octets conservés par L3-A (`MAX_ITEMS`, `MAX_CONTENT_BYTES`, `MAX_TOTAL_CONTENT_BYTES` de L3-A restent la borne dure ; un `BAD_TREE` devient `OBSERVATION_REFUSED`). Pas de délai d'horloge (déterminisme) ; l'interruption de processus ne laisse aucune écriture à réparer (section 4.12).

**4.5 Scans instables.** La double passe de B2 est conservée telle quelle (`max_attempts` fourni, essais bornés, puis `UNSTABLE_LISTING`). Le protocole **n'ajoute aucune boucle de nouvelle tentative** : une instabilité, un écart de rescan ou une erreur structurelle donne un rapport `REFUSED` ; relancer est un nouvel appel conscient, sans mémoïsation. Deux classes d'issue, à ne pas confondre : un **refus** (structurel : le scan ou la requête est inutilisable) n'expose **aucun** statut de couche (`inventory`, `chain_checks` = `NOT_BUILT`) ; un **blocage** (sémantique : le scan est recevable mais dit « incomplet », « chaîne incohérente »…) conserve `RECEIVABLE` et tous les statuts des couches terminées (section 6).

**4.6 Rattachement du manifeste et des ValidationRun.** Le manifeste est celui **observé par le scan S1** (v6 : indexé par label de racine, lu strictement, conforme au schéma de B3, propre à la campagne). Le protocole ne lit pas `manifest.json` lui-même. Pour chaque racine `CAMPAIGN_DIR`, `expected_run_id = <campaign_id>_walk_forward` (convention de L3-A) ; la chaîne est vérifiée si le manifeste déclare `walk_forward_validation_run_id`, ou si **toute** entrée existe sous `validations/` ou `walk_forward/` (y compris un second run ou un run étranger : `MIXED_RUNS` / `FOREIGN_CAMPAIGN` de L3-A ne doivent pas être perdus) ; sinon `chain_coherence = NOT_EVALUATED` avec la catégorie d'`emptiness`. Les runs Monte-Carlo / stabilité référencés sont **présents ou absents** (v6) mais **non qualifiés** : `auxiliary_runs = UNQUALIFIED`, aucune raison v5 levée.

**4.7 Fichiers de preuve L2.** Contrôlés exclusivement par L3-A sur les octets conservés **du scan S1** (couverture, sessions, sceau, `validation_run.json` ; hashs d'octets bruts, références croisées, exhaustivité des sorties observées face au sceau, absence d'inconnu/anomalie/orphelin). Le protocole n'ajoute aucune lecture des fichiers de preuve : une seconde lecture serait un second jeu de faits. Les fichiers sont à nouveau couverts par le **rescan S2** (leurs `content_hash` entrent dans la projection de faits).

**4.8 Appel de L3-A.** `observed_tree_from_scan` reçoit uniquement des `ExposureScan` pris dans `interpretation.scans` (S1). Le protocole contrôle avant l'appel : `scan.rules_digest` = digest `CAMPAIGN_DIR` de v6 = `gate_v_k1s2_verifier.TABLE_DIGEST` (trois littéraux, comparés à l'exécution : si v6 diverge de v5 un jour, `observed_tree_from_scan` lève `ObservationRefused(BAD_TREE)` — converti en `OBSERVATION_REFUSED` — au lieu d'être silencieusement faux ; `WRONG_TABLE` de `verify_run_chain` n'est atteignable que par un arbre construit à la main), `hooks_used` faux, `limits` égales à la requête, et `hash_limits` égales à la requête **seulement pour une disposition dont la table est hachée** (`CAMPAIGN_DIR`) et `None` sinon (B3 pose `applied = None` pour `RESULTS` et `SPLIT_PLAN_DIR`, et B5 refuse un pin `hash_limits` sur une table non hachée). Après conversion, il recalcule indépendamment la projection `(chemin, nature, sha256)` de la racine depuis `scan.observations` et exige l'égalité avec celle de l'arbre observé (`OBSERVATION_PROJECTION_MISMATCH`) : une conversion qui perdrait une entrée est détectée. Tout défaut de `ChainVerification` donne `CHAIN_INCOHERENT` (défauts conservés) ; un `established` ne donne **aucun** statut positif d'exclusion.

**4.9 Diagnostic des répertoires vides.** `diagnose_emptiness` est appelé **pour chaque racine `CAMPAIGN_DIR`**, sans condition. `absence_consideration_blocked` (B, C, CONTRADICTORY, UNRESOLVED_ENTRIES, BAD_INPUT) donne le blocage `EMPTINESS_BLOCKING`. Catégories A et NOT_EMPTY : aucun blocage, mais `absence_evidence` reste `UNAVAILABLE` (l'absence de blocage n'est pas une autorisation). Le comportement « un répertoire de sortie vide est un squelette bloquant » (N-VIDE-3, déjà vrai en v5/v6) est **supposé, jamais décidé** ici : un test de caractérisation détecte tout changement (section 10, AT-14).

**4.10 Reconstruction de l'inventaire B4 (N2-b).** Le complete de B4 **diffère** de celui de B3 (il ajoute les raisons de registre et `REASON_NO_STATIC_ROOT`) : le rapport porte les deux (`b3_completeness`, `inventory_b4`). Le protocole lit le registre par `read_registry(root, barrier=True)` (lecture stricte de la chaîne entière), dérive `OwnCampaignContext` (étage), construit les vues de registre et de comptabilité par un **adaptateur de lecture à créer** (aucun producteur n'existe, section 2), puis appelle `assemble_exposure_inventory(interpretation_S1, …)`. B4 « n'élargit jamais la complétude de B3 » (invariant déjà imposé par son constructeur) : le protocole le ré-affirme. Tête de chaîne du registre relue en fin d'audit (`REGISTRY_CHAIN_HEAD_CHANGED` si elle a bougé).

**4.11 Épinglage A0/B5 (N2-b).** Le protocole appelle `build_exposure_inventory_record` (pur), puis la relecture comme le fait `publish_exposure_inventory` avant d'écrire, et refuse tout A0 que B5 refuserait (`A0_RECORD_REFUSED`). **Écart d'interface** : seul `parse_strict_record` (niveau JSON) est public ; la relecture schéma + identités (`_prove_rereadable`, `_parse_record`) est privée et B5 n'a pas d'`__all__`. Soit B5 expose une fonction publique de vérification de relecture (amendement de B5, interdit sans décision), soit le protocole importe un nom privé (dépendance fragile, assumée) : décision D13. Il vérifie que `scan_pins` du record égalent la requête : `rules_digest` de la disposition, `limits`, `hash_limits` (obligatoires pour une table hachée), `hooks_used` faux, racines résolues (`A0_PIN_MISMATCH`). La **publication est un acte séparé** (`publish_audit_a0`, mince, qui refuse un rapport refusé ou à hooks) ; l'audit lui-même n'écrit rien. **Attention** : le chargeur de lignée B6 (`gate_v_exposure_declarations.py`, ligne 871) charge **tout** A0 de `exposure/` par `load_exposure_inventory`, sans contrôle de `rules_versions` (et `RulesVersions.is_current()` n'a aucun appelant de production). Un A0 v6 publié serait donc consommé par B6 sans que rien ne distingue v4 de v6, et les A0 v4 historiques restent consommables sans audit : « obligatoire » ne couvre pas cette voie. `publish_audit_a0` est donc **différé** tant que le gating de B6 n'est pas décidé (D12). Le format A0 reste 1/2 : le rapport d'audit n'est **pas** persisté dans l'A0 (un format 3 et un fichier annexe exigeraient une nouvelle table B3, car tout fichier inconnu d'un dossier de campagne est bloquant au scan suivant — décision D6).

**4.12 Refus fermé.** Tout chemin non prévu est un refus typé ; aucune `Exception` ne s'échappe du point d'entrée. Les `BaseException` (`KeyboardInterrupt`, `SystemExit`) se propagent telles quelles, sans écriture à défaire puisque l'audit est en lecture seule. Un refus structurel ne produit ni `assembly`, ni statut de couche. Pas de repli (« si le rescan échoue, utiliser S1 seul ») : jamais.

**4.13 Mêmes faits pour B3, L3-A et B5, et détection d'un changement entre scans.**
- *Par construction* : un seul scan S1 alimente B3 (findings), L3-A (arbre), B4 et B5 (`scan_pins`). Le protocole n'appelle jamais `scan_audit_roots` directement : seulement via `interpret_audit_roots_v6`, exactement **deux fois par groupe de disposition** (S1 puis S2) — un test espionne ce compte.
- *Par confrontation* : la **projection de faits** `F(scan)` = SHA-256 du JSON canonique de, par racine triée, `(label, may_be_empty)`, `rules_digest`, `limits`, `hash_limits`, et par observation triée par chemin : `(chemin, nature, classe, anomalie, rule_tag)` pour **toutes** les entrées, plus `(taille, content_hash)` pour les seuls fichiers de classe **lue ou hachée** (même périmètre que `_comparable` de B2). Les fichiers inertes, inconnus, orphelins et les répertoires ne sont donc comparés que par leur nom, comme en B2 : un journal vivant (`logs.txt`) sous une racine `RESULTS` ne produit pas de dérive systématique. Une seconde projection d'**identité** `I(scan)` ajoute `mtime_ns`, `st_ino`, `st_dev` pour ces mêmes fichiers lus ou hachés seulement. `F1 ≠ F2` → `RESCAN_FACT_DRIFT` ; `F1 = F2` mais `I1 ≠ I2` → `RESCAN_IDENTITY_DRIFT` (conservateur : un fichier lu ou haché retouché à contenu égal est refusé, jamais accepté en silence). Un fichier **inerte** modifié sans changer de nom reste invisible : limite assumée (T1).
- *Ce que F1 = F2 ne prouve pas* : un double scan identique **n'est pas** un instantané atomique, **ne fournit aucune chronologie**, ne détecte ni une modification restaurée à l'identique entre S1 et S2, ni une modification postérieure à S2, ni une édition masquée par une résolution grossière de `mtime` (FAT, exFAT, partages réseau). `AuditReport.rescan` s'appelle `PROTOCOL_RESCAN_MATCHED`, jamais « vérifié » ni « indépendant » ; `snapshot_atomicity` et `chronology` figurent dans `not_proven`.
- *Rescan indépendant au sens E3-J* : exécuté par un acteur distinct (processus et identité distincts, plus tard, avec preuve de temps). Le protocole ne le prétend jamais (`independent_rescan_required = True`, constant) ; son S2 sert uniquement à détecter un changement pendant l'audit et à exiger que S2 soit un appel **frais** (racines reconstruites, aucun objet de S1 réutilisé : `RESCAN_NOT_DISTINCT`).

## 5. Politique de version

Trois axes **distincts**, jamais confondus :

| Axe | Objet | Valeur actuelle | Qui le change | Effet |
|---|---|---|---|---|
| Version **scientifique** | `b3_interpreters` (v4/v5/v6), E3-A, B4 | `RulesVersions.is_current()` ↔ v4 | décision d'activation de l'utilisateur | définit ce qu'un inventaire *signifie* |
| Format de **persistance** | A0 format 1 / 2 | 1 (sans table hachée), 2 (avec `hash_limits`) | décision de format distincte | définit comment il s'*écrit* |
| Version du **protocole** | `AUDIT_PROTOCOL_VERSION` (proposé : `gate_v_audit_protocol_v1`) | n/a | cette conception | définit l'ordre et les refus de l'audit |

Règles :
1. **Plancher** : `AUDIT_B3_ACCEPTED = ("gate_v_exposure_interpreters_v6",)` — liste blanche explicite, pas de `>=` sur des chaînes. Une v7 n'est acceptée qu'en l'ajoutant par une décision.
2. **v4 et v5** : lecture historique autorisée (B5), jamais produits ni acceptés par l'audit (`VERSION_BELOW_MINIMUM`). Aucune réécriture.
3. **A0 ancien** : toujours lisible par B5, **jamais requalifié automatiquement** : `RulesVersions.is_current()` reste lié à v4 ; l'activation de v6 par l'audit **ne change pas** `is_current()` (décision D3 séparée).
4. **Pas de relabelling recevable** : le champ `b3_interpreters` d'un A0 persisté est une déclaration non authentifiée (même `rules_digest` pour v5 et v6 ; falsification avec recalcul d'authenticité démontrée par les deux tests de caractérisation de la publication précédente). Un A0 historique n'est donc **jamais** une attestation : le rapport le liste sous `historical_a0` avec `qualification = NOT_REQUALIFIED` ; la seule requalification est un **nouvel audit** dont l'`inventory_id` (qui inclut `complete`, donc la sévérité de v6) est comparé à celui de l'A0 — l'égalité des identités n'importe aucune garantie de version, une différence prouve la non-équivalence.
5. **Aucune activation silencieuse** : B3 v4/v5, B4, B5, E3-A et les modules de déclarations ne sont pas modifiés ; v6 n'est sélectionné que par le protocole (graphe d'imports verrouillé, section 10 AT-12). Les consommateurs historiques ne **sélectionnent** pas v6. Réserve (D12) : un A0 v6 un jour publié serait **lu** par B6 sans contrôle de version (`load_exposure_inventory`, aucun appelant de production de `is_current()`) ; c'est pourquoi la publication d'A0 par l'audit est différée.
6. **Identité de table** : l'égalité des digests v5/v6 est un fait mesuré, pas une règle. Le protocole la contrôle à l'exécution (4.8) ; si les tables divergent, L3-A doit recevoir une version propre avant tout usage (obligation notée, non traitée ici).

## 6. Statuts et autorités : `AuditReport`

Vocabulaire fermé, **un axe par question**, aucun booléen générique. **Périmètre et méthode du contrôle de vocabulaire** (alignés sur le test existant de L3-A, `test_gate_v_k1s2_verifier.py:118-124`, qui est un contrôle de *sous-chaînes* sur les valeurs d'énumération et sur les noms publics du module) : sous-chaînes interdites dans les valeurs d'énumération et les identifiants publics : `FRESH`, `NO_OVERLAP`, `ADMIT`, `ADMISSION`, `CLAIM`, `AUTHORI`, `ABSENCE_ESTABLISHED`, `EXCLUSION` ; **jetons** interdits (découpage sur `_`, pour ne pas condamner `REQUEST_INVALID` ni `SCAN_HOOKS_PRESENT`) : `PASS`, `OK`, `VALID`, `CLEAN`, `CLEARED`, `ALLOWED`, `GRANTED`, `ACCESS`. Le champ s'appelle donc `absence_evidence` (et non `exclusion_proof`). Seule exemption, déclarée et figée en littéraux par le test : le tuple `e3j_prerequisites_unmet`, qui *nomme* ce qui manque (`AUTHORIZATION`, `ADMISSION_WRITER`, `RESERVATION_TIME_PROOF`…) et n'est ni une énumération ni un identifiant.

Deux classes d'issue (section 4.5) : les **refus** (`refusals`, structurels, codes de la section 8 marqués « refus ») rendent `receivability = REFUSED` et laissent `inventory`, `chain_checks`, `emptiness` à `NOT_BUILT` ; les **blocages** (`blocks`, sémantiques) laissent `RECEIVABLE` et conservent tous les statuts des couches terminées. Un blocage n'est jamais présenté comme un refus, ni l'inverse.

| Champ | Valeurs | Signification — et ce qu'elle n'est pas |
|---|---|---|
| `receivability` | `RECEIVABLE` / `REFUSED` | le scan et la requête sont structurellement recevables ; **pas** « sain » |
| `refusals` | tuple d'`AuditDefect` (code fermé, couche, chemin, détail ≤ 300 car.) | vide ⇔ `RECEIVABLE` |
| `blocks` | tuple d'`AuditBlock` (code fermé `CHAIN_INCOHERENT` / `EMPTINESS_BLOCKING`, `root_label`, détail ; chaque blocage empêche toute preuve d'absence future, sans portée distincte en N2-a) | ce qui bloque l'aval ; peut coexister avec `RECEIVABLE` |
| `window_provenance` | `UNVERIFIED` (seule valeur de N2-a) | `W` est configurée par l'opérateur et **non revalidée** (section 4.1) ; `window_declared_source = OPERATOR_CONFIGURED` en rappelle l'origine |
| `manifest_state` | par racine `CAMPAIGN_DIR` : `ABSENT` / `INITIAL` / `RUNNING` / `TECHNICAL_FAILURE` / `EVIDENCE_INCOMPLETE` / `EVIDENCE_COMPLETE` / `UNREADABLE_OR_NONCONFORMING` / `FOREIGN` | expose ce qui rend deux rapports « complets » *différents* : un manifeste initial (cas 1) et l'absence de tout manifeste (cas 19, légale et FRESH-éligible en v6) |
| `observed_execution_artefacts` | par racine : nombre d'entrées sous `validations/` et `walk_forward/` | `COMPLETE` ne cohabite qu'avec « aucun artefact d'exécution observé » : tout artefact Walk-Forward lève `RUN_*_UNVERIFIED` (`INCOMPLETE`) |
| `b3_completeness` | `COMPLETE` / `INCOMPLETE` / `NOT_BUILT` | recopie de `complete` de l'interprétation B3 v6 ; **pas** une absence d'exposition |
| `inventory_b4` | `COMPLETE` / `INCOMPLETE` / `NOT_BUILT` | `complete` de B4 (ajoute registre et `REASON_NO_STATIC_ROOT`) ; `NOT_BUILT` en N2-a |
| `incomplete_reasons` | raisons B3 (et B4) intactes | jamais filtrées ni levées |
| `chain_checks` | par racine : `COHERENT` / `INCOHERENT` / `NOT_EVALUATED`, défauts L3-A, catégorie d'`emptiness` | cohérence avec les observations fournies — **pas** lecture réelle, exclusivité, antériorité, absence d'exposition |
| `rescan` | `PROTOCOL_RESCAN_MATCHED` / `DRIFT` / `NOT_PERFORMED` + `F1`, `F2`, `I1`, `I2` | stabilité observée sur deux appels — **pas** instantané, **pas** chronologie |
| `absence_evidence` | constante `UNAVAILABLE` | aucune preuve d'absence scientifique n'existe (23.30.1 ; aucun producteur) |
| `auxiliary_runs` | constante `UNQUALIFIED` | MC / PS non qualifiés |
| `s0_facts` | constante `NOT_VERIFIED` | L3-B absent |
| `e3j_prerequisites_unmet` | tuple **non vide**, constant : `INDEPENDENT_RESCAN`, `CHRONOLOGY_PROOF`, `SEAL_ANTERIORITY`, `D5_PREDICATE`, `S0_RECOMPUTATION`, `INVENTORY_CONTENT_DIGEST_RECHECK`, `ATTESTATION`, `AUTHORIZATION`, `COMMITMENT`, `RESERVATION_TIME_PROOF`, `REGISTRY_CHAIN_STRICT_READ`, `ADMISSION_WRITER` | ce que l'audit n'a pas fait ; liste reprise des obligations déjà écrites (préconditions, L3-A §6) |
| `not_proven` | `NOT_PROVEN` de L3-A + `SNAPSHOT_ATOMICITY`, `CHRONOLOGY`, `INDEPENDENT_RESCAN`, `S0_RECOMPUTATION` | constant |
| `grants` | `()` | le rapport n'accorde **rien** ; propriété `grants_nothing` toujours vraie |
| `historical_a0` | par A0 : hash, `rules_versions`, `NOT_REQUALIFIED` | lecture historique |

Les champs constants (`absence_evidence`, `auxiliary_runs`, `s0_facts`, `grants`, `e3j_prerequisites_unmet`, `not_proven`) portent peu d'information en eux-mêmes : leur valeur est d'être **verrouillés** (AT-04 : un test de mutation sur ces constantes), les champs informatifs étant `manifest_state`, `observed_execution_artefacts`, `blocks`, `chain_checks`, `rescan`.

Aucun statut positif de ce lot ne signifie : FRESH démontré, NO_OVERLAP établi, RESERVATION autorisée, ADMISSION autorisée, FINAL_HOLDOUT accessible, Gate V franchie. Le rapport n'expose **aucune** sérialisation ni empreinte publique (ni `canonical_bytes`, ni `report_digest`, ni `to_*` / `from_*`) : un sérialiseur public plus un flux vers l'aval en feraient un justificatif transportable. Les tests comparent des rapports par l'égalité des dataclasses gelées et recalculent leurs propres empreintes.

## 7. Diagramme de séquence

```mermaid
sequenceDiagram
    autonumber
    participant C as Appelant (E3-J futur)
    participant P as gate_v_audit_protocol
    participant B3 as B3 v6 (+B2 double passe)
    participant L as L3-A (obs, emptiness, verifier)
    participant R as Registre (lecture stricte, N2-b)
    participant B4 as B4 (N2-b)
    participant B5 as B5 (pur, N2-b)
    C->>P: audit_campaign_exposure(AuditRequest)
    P->>P: requête : types, plafonds explicites, budget, racines configurées
    P->>B3: interpret_audit_roots_v6(racines fraîches, limits, hash_limits, W)
    B3-->>P: S1 (SourceInterpretation) ou erreur structurelle/instable -> refus typé
    P->>P: recevabilité : version liste blanche, table, hooks, limits, racines
    loop chaque racine CAMPAIGN_DIR
        P->>L: observed_tree_from_scan(scan de S1)
        P->>L: diagnose_emptiness(arbre)
        P->>L: verify_run_chain(arbre, run attendu)
    end
    P->>P: projections F1/I1, égalité arbre = scan
    opt N2-b
        P->>R: read_registry(barrier=True) ; étage dérivé
        P->>B4: assemble(S1, vues du registre, contexte)
        P->>B5: record pur + relecture stricte + pins
    end
    P->>B3: interpret_audit_roots_v6(racines RECONSTRUITES) = S2
    P->>P: F2 = F1 ? I2 = I1 ? ; tête du registre inchangée ?
    P-->>C: AuditReport (refus ou blocages typés, statuts par axe, grants = ())
    Note over C,P: C relance l'audit au moment de publier ; le rapport n'est pas un justificatif
```

## 8. Matrice de refus

Classe : **R** = refus structurel (`REFUSED`, aucun statut de couche) ; **B** = blocage sémantique (`RECEIVABLE` conservé, statuts des couches terminées exposés, portée dans `AuditBlock`). « Atteignable » : **P** par l'interface publique ; **D** défensif, atteignable seulement par la couture privée `_audit` (section 10).

| Code | Classe | Atteignable | Condition | Source de la preuve | Portée |
|---|---|---|---|---|---|
| `REQUEST_INVALID` | R | P | type, champ manquant, plafond non positif, `HashLimits` incohérent | validation de requête | tout |
| `HASH_LIMITS_MISSING` | R | P | `hash_limits` absents (B3 v5/v6 les exigent pour tout appel) | requête | tout |
| `RESOURCE_BUDGET_EXCEEDED` | R | P | majorant de lecture (par disposition, S1 + S2) > budget | requête | tout |
| `ROOT_FOREIGN` | R | P (nom ≠ `expected_name`, identité `st_dev`/`st_ino` changée entre S1 et S2) / D (hors configuration) | racine étrangère | B2 / L3-A / protocole | tout |
| `WINDOW_MISMATCH` | R | P | `W` ≠ frontière `final_holdout` du split plan référencé (ou fenêtre du registre, N2-b) | chargeurs stricts | tout |
| `SCAN_STRUCTURAL_FAILURE` (+ code B2) | R | P | lien, FIFO, nom non portable, collision de casse, plafond dépassé, racine absente/vide | B2 | tout |
| `SCAN_UNSTABLE` | R | P | `UNSTABLE_LISTING` après `max_attempts` | B2 | tout |
| `SCAN_HOOKS_PRESENT` | R | D | `hooks_used` vrai | scan | tout |
| `SCAN_TABLE_MISMATCH` | R | D | `rules_digest` ≠ table v6 de la disposition ou ≠ `TABLE_DIGEST` de L3-A | scan, constantes | tout |
| `SCAN_LIMITS_MISMATCH` | R | D | `scan.limits` ≠ requête ; `hash_limits` ≠ requête **pour une disposition hachée** (`None` attendu sinon) | scan | tout |
| `VERSION_BELOW_MINIMUM` | R | D | `semantics_version` ∉ liste blanche | interprétation | tout |
| `OBSERVATION_REFUSED` | R | P/D | `ObservationRefused` (`BAD_TREE`, `BAD_PATH`…) | L3-A | racine |
| `OBSERVATION_PROJECTION_MISMATCH` | R | D | arbre observé ≠ projection du scan | recalcul du protocole | racine |
| `RESCAN_NOT_DISTINCT` | R | D | S2 réutilise un objet de S1 | protocole | tout |
| `RESCAN_STRUCTURAL_FAILURE` | R | P | erreur B2 pendant S2 | B2 | tout |
| `RESCAN_FACT_DRIFT` | R | P | `F1 ≠ F2` | projections | tout |
| `RESCAN_IDENTITY_DRIFT` | R | P | `F1 = F2`, `I1 ≠ I2` | projections | tout |
| `REGISTRY_UNREADABLE` (N2-b) | R | P | chaîne illisible ou rompue | `read_registry` | tout |
| `REGISTRY_CHAIN_HEAD_CHANGED` (N2-b) | R | P | tête de chaîne début ≠ fin | registre | tout |
| `STAGE_NOT_DERIVABLE` (N2-b) | R | P | étage propre non déterminé de façon unique | registre | tout |
| `CHAIN_INCOHERENT` | B | P | au moins un `Defect` L3-A (codes conservés) | L3-A | `ABSENCE_EVIDENCE` |
| `EMPTINESS_BLOCKING` | B | P | catégorie B, C, CONTRADICTORY, UNRESOLVED_ENTRIES, BAD_INPUT | L3-A emptiness | `ABSENCE_EVIDENCE` |
| `A0_RECORD_REFUSED` (N2-b) | B | P | B5 refuserait l'enregistrement (taille, schéma, hachée sans `hash_limits`, hooks) | B5 | `PUBLICATION` |
| `A0_PIN_MISMATCH` (N2-b) | B | P | `scan_pins` ≠ requête | record | `PUBLICATION` |

Statuts **ni refus ni blocage** (visibles, à lire par l'aval) : `b3_completeness` / `inventory_b4 = INCOMPLETE`, `chain_checks = NOT_EVALUATED`, `emptiness ∈ {A, NOT_EMPTY}`, `manifest_state`, `absence_evidence = UNAVAILABLE`, `e3j_prerequisites_unmet ≠ ()`.

## 9. Matrice scientifique des cas de test futurs

« Aujourd'hui » = comportement déjà mesuré et testé (v6, L3-A, B5) ; « N2 » = à écrire avec le protocole. Résultat attendu = refus et/ou statut ; la colonne preuve nomme l'élément qui rend le test non tautologique (littéral indépendant, mutant, oracle écrit à part).

| # | Cas | Observations / mise en place | Refus ou statut attendu | Preuve nécessaire |
|---|---|---|---|---|
| 1 | Manifeste initial légitime | READY, révision 0, aucun artefact, `validations/` et `exposure/` vides | `RECEIVABLE`, `b3_completeness COMPLETE` si le reste l'est, `manifest_state INITIAL`, `observed_execution_artefacts 0`, `emptiness A`, `chain NOT_EVALUATED`, **`absence_evidence UNAVAILABLE`**, prérequis E3-J non vides | aujourd'hui : scénario v6 « initial » ; N2 : le rapport ne contient aucun mot de verdict |
| 2 | RUNNING | statut RUNNING, `validations/` vide | `b3_completeness INCOMPLETE` (raison `MANIFEST_RUN_IN_PROGRESS:<racine>/manifest.json#status`), `emptiness C` ⇒ blocage `EMPTINESS_BLOCKING` | scénarios v6 + L3-A (aujourd'hui) ; N2 : conversion en blocage |
| 3 | TECHNICAL_FAILURE | **deux scénarios** : (a) synthétique, manifeste seul ; (b) producteur D2 réel, avec `technical_failure.json` et `manifest.update.lock` | (a) `INCOMPLETE` (`MANIFEST_TECHNICAL_FAILURE:…#status`), `emptiness C`, aucun finding créé ; (b) idem **plus** deux findings `UNKNOWN_SOURCE` bloquants (ces deux fichiers sont inconnus de la table : `interpreters.py:190`) | idem ; l'assertion « aucun finding » n'est valable qu'en (a) |
| 4 | Révision incohérente | READY, `manifest_revision > 0` | `INCOMPLETE` (`ready_vs_revision`) ; noter : `emptiness` ne contrôle pas la révision, seule v6 la voit | aujourd'hui (v6) ; N2 : le protocole n'affaiblit pas cette raison (sur-ensemble) |
| 5 | Run déclaré absent | manifeste déclare le run WF, `validations/` vide ou absent | `INCOMPLETE` (`MANIFEST_RUN_ABSENT:<racine>/manifest.json#walk_forward_validation_run_id->validations/<run>/validation_run.json`), `emptiness B` ⇒ `EMPTINESS_BLOCKING` | aujourd'hui ; c'est le cas FRESH-éligible à tort en v4/v5 : la couture privée prouve que v4/v5 sont refusés (`VERSION_BELOW_MINIMUM`, atteignable seulement par `_audit`) |
| 6 | Chaîne L2 partielle | `validation_run.json` sans sceau, ou sans session | `INCOMPLETE` (`MANIFEST_RUN_EVIDENCE_MISSING:…`), blocage `CHAIN_INCOHERENT` (`NO_SEAL` / `SESSION_MISSING`) | aujourd'hui ; N2 : codes L3-A conservés dans `blocks` |
| 7 | Chaîne cohérente mais construite a posteriori | chaîne complète et croisée, sceau écrit après coup | `chain COHERENT` **sans** blocage de chaîne, mais `b3_completeness INCOMPLETE` (`RUN_*_UNVERIFIED` non levées), `absence_evidence UNAVAILABLE`, `SEAL_ANTERIORITY` ∈ `not_proven` et ∈ `e3j_prerequisites_unmet` | N2 : test explicite « cohérent ≠ exclu » ; limite documentée, **aucun test n'affirme la non-détection** |
| 8 | Couverture d'un autre run | `run_data_coverage.json` d'un run voisin | `CHAIN_INCOHERENT` (`COVERAGE_NOT_ATTRIBUTABLE`) | aujourd'hui (L3-A) |
| 9 | Sortie Walk-Forward omise du Seal | fichier sous `walk_forward/` absent du sceau | `CHAIN_INCOHERENT` (`OUTPUT_UNSEALED`) | aujourd'hui (L3-A) |
| 10 | Fichier ajouté après le scan | fichier **de nom portable** (une entrée inconnue, anomalie `UNKNOWN_FILE`, pas un échec structurel — sinon on obtiendrait `RESCAN_STRUCTURAL_FAILURE`) créé après S1, avant S2, par un interpréteur de test injecté via la couture privée `_audit` | `RESCAN_FACT_DRIFT` ; ajout **après** S2 : non détecté (T1, documenté, non testé comme garantie) | N2 ; aucun point d'injection dans l'API publique |
| 11 | Fichier changé entre deux lectures | modification pendant S1 | B2 : essai recommencé puis `SCAN_UNSTABLE` ; modification entre S1 et S2 d'un fichier lu ou haché : `RESCAN_FACT_DRIFT` ; `touch` seul : `RESCAN_IDENTITY_DRIFT` ; fichier **inerte** modifié sans changer de nom : non vu (T1) | aujourd'hui (B2) + N2 |
| 12 | Scan avec hooks | tentative de passer `ScanHooks` | impossible par signature ; si l'interpréteur de test renvoie un scan à hooks : `SCAN_HOOKS_PRESENT` | N2 : test de signature (AST) + test défensif via `_audit` |
| 13 | Objet `ExposureScan` forgé | objet construit à la main avec bons digests | non acceptable en entrée (signature). Via `_audit`, un scan forgé **cohérent aux deux appels** est indistinguable (limite T2) ; un scan forgé seulement à S1 est vu comme dérive à S2 | N2 : test de la dérive à S2 uniquement ; **la limite est documentée, pas gravée par un test vert de non-détection** |
| 14 | A0 historique | A0 de B3 v2 / v4 / v5 relu | lu, listé `NOT_REQUALIFIED`, jamais utilisé comme preuve | aujourd'hui (B5) + N2 |
| 15 | Relabelling v5 ↔ v6 | A0 v5 relabellisé v6 avec recalcul d'authenticité | l'A0 est lu mais **non qualifié** ; un nouvel audit v6 donne un `inventory_id` différent si la sévérité diffère | aujourd'hui : 2 tests de caractérisation ; N2 : comparaison d'`inventory_id` |
| 16 | `HashLimits` absents ou contradictoires | absents ; `max_hashed_file_bytes` > total | `HASH_LIMITS_MISSING` / `REQUEST_INVALID` **avant** tout accès disque ; A0 d'une table hachée sans pin : refus B5 | aujourd'hui (B2, B5) + N2 (ordre : refus avant lecture) |
| 17 | Racine étrangère | dossier dont le nom ≠ `expected_name` ; manifeste d'une autre campagne ; campagne dérivée légitime à côté de la campagne propre (doit être **acceptée**, pas refusée) | `ROOT_FOREIGN` / `MANIFEST_RUN_FOREIGN` / `FOREIGN_MANIFEST` pour les deux premiers ; aucun refus pour le troisième | aujourd'hui (v6, L3-A) + N2 |
| 18 | Résultats MC / PS non qualifiés | MC et PS présents, chaîne WF complète | `auxiliary_runs UNQUALIFIED`, aucune raison v5 levée | aujourd'hui (règle H de v6) ; N2 : constante |
| 19 | Répertoire vide sans déclaration | `validations/` et `exposure/` vides, **aucun** `manifest.json` (légal : l'ancre de `CAMPAIGN_DIR` est `plan.json`) | `RECEIVABLE`, `b3_completeness COMPLETE` (v6 ne crée aucune attente sans manifeste), `manifest_state ABSENT`, `emptiness A`, **aucune** absence établie ; ce rapport diffère du cas 1 par `manifest_state` | aujourd'hui (L3-A, note N-VIDE-1 §4 bis) ; N2 : `manifest_state` rend la différence lisible |
| 20 | Répertoire vide contredisant le manifeste | manifeste déclare un run, dossier de run vide | `emptiness B` ⇒ blocage `EMPTINESS_BLOCKING` | aujourd'hui |
| 21 | Données S0 non vérifiées | couverture citant un `loaded_content_sha256` quelconque | `s0_facts NOT_VERIFIED`, `S0_RECOMPUTATION` ∈ prérequis | N2 : constante ; L3-B reste hors périmètre |
| 22 | Accès FINAL_HOLDOUT non autorisé | tentative de lier l'audit au Claim ; campagne contenant `final_holdout_access_claim.json` | aucun import du protocole vers les modules de Claim / registre-écriture (AST) ; un Claim présent est vu comme source exposante par B3/E3-A, jamais ignoré | N2 : test d'imports + scénario de Claim présent |

## 10. Tests d'acceptation (à écrire avant le code, rouge puis vert)

Couture de test = **l'interface publique du protocole** (requête → rapport) pour tous les refus et blocages de classe P (section 8), et la **couture privée** `_audit(request, *, _interpreter)` pour les refus défensifs de classe D (version non admise, hooks, table, limites du scan, projection, rescan non distinct), qui ne sont pas atteignables autrement : elle reçoit un interpréteur de test, n'est exportée nulle part, et AT-12 interdit à tout autre module de la référencer. Les internes sont testés par leurs suites existantes. Chaque test a un oracle indépendant (littéraux, projection recalculée à part).

- **AT-01 (signature)** : AST — `audit_campaign_exposure` n'a aucun paramètre de type scan / arbre / interprétation / inventaire / hooks ; tout argument hostile donne `REFUSED`, jamais d'exception.
- **AT-02 (un seul scan)** : espion sur `scan_audit_roots` **tel que lié dans le module de v5** (`gate_v_exposure_interpreters_v5.scan_audit_roots`, importé par nom : patcher le module du scan serait sans effet) — appelé exactement 2 fois par groupe de disposition (S1 + S2) ; L3-A ne reçoit que des scans de S1.
- **AT-03 (faits partagés)** : l'arbre de L3-A, les findings de B3 et les `scan_pins` de B5 dérivent du même `F1` ; mutant : substituer un scan modifié à L3-A ⇒ `OBSERVATION_PROJECTION_MISMATCH` ou `RESCAN_FACT_DRIFT`.
- **AT-04 (tableau de la section 9)** : un test par cas, attendus littéraux (codes de raison exacts au format `CODE:<racine>/manifest.json#<référence>`) ; test de **mutation** sur les constantes (`absence_evidence`, `auxiliary_runs`, `s0_facts`, `grants`, `e3j_prerequisites_unmet`, `not_proven`) : changer ou vider l'une d'elles fait échouer un test (une clause « jamais positif si constante ≠ … » serait vide).
- **AT-05 (vocabulaire)** : contrôle de sous-chaînes et de jetons de la section 6, sur les valeurs d'énumération et les identifiants publics ; exemption figée en littéraux pour `e3j_prerequisites_unmet` ; `grants == ()`.
- **AT-06 (rescan frais)** : S2 construit avec des objets nouveaux ; réutiliser un objet de S1 ⇒ `RESCAN_NOT_DISTINCT`.
- **AT-07 (dérive)** : fichier ajouté, supprimé, modifié, touché entre S1 et S2 ⇒ le code attendu (via la couture privée pour l'injection entre S1 et S2). Les limites T1/T2 (ajout après S2, scan forgé cohérent) sont **documentées en section 15 et dans `not_proven`**, sans test vert qui graverait la non-détection comme comportement attendu.
- **AT-08 (plafonds)** : aucune valeur par défaut (AST) ; budget dépassé ⇒ refus avant accès disque (aucun `open` : espion).
- **AT-09 (pureté et lecture seule)** : l'audit n'écrit rien (hash de l'arbre de test avant/après, y compris en cas de refus et d'interruption simulée) ; pas d'horloge ni de réseau.
- **AT-10 (versions)** : via `_audit` avec un interpréteur v4 / v5 de test ⇒ `VERSION_BELOW_MINIMUM` (aucun chemin public n'y mène : la fonction publique n'appelle que v6) ; v6 accepté ; `is_current()` inchangé ; une « v7 » ⇒ refus ; digests v5 = v6 contrôlés à l'exécution, divergence simulée ⇒ `SCAN_TABLE_MISMATCH`.
- **AT-11 (A0, N2-b)** : record pur relisible ; pins égaux à la requête ; hachée sans `hash_limits` ⇒ refus ; aucun fichier créé par l'audit.
- **AT-12 (graphe d'imports)** : seuls le protocole et B5 importent `gate_v_exposure_interpreters_v6` (hors tests) ; seul le protocole importe `gate_v_k1s2_*` ; le protocole n'importe aucun module de Claim ni d'écriture de registre ; B3 v4/v5/B4/E3-A n'importent pas le protocole ; nul autre module ne référence `_audit`. **Ce garde-fou entre en conflit avec un test existant** (section 11).
- **AT-13 (non-régression historique)** : suites B2/B3/B5/L3-A vertes et identités historiques gelées, **à l'exception d'un test à amender** (section 11, D11).
- **AT-14 (N-VIDE-3 supposé)** : un répertoire de sortie vide reste un squelette bloquant en v6 ; tout changement fait échouer ce test (décision séparée requise).
- **AT-15 (mutation ciblée)** : harnais jetable, une seule instance, sur le protocole (ordre des appels, égalité F, filtre des versions, recopie de `complete`, constantes) ; survivants équivalents prouvés ; copie construite depuis `git archive` avec les paquets nécessaires (leçon de la publication précédente).
- **AT-16 (Windows / POSIX)** : liens, FIFO, jonctions : cas marqués explicitement ; exécution Linux requise (section 12) avant d'affirmer la couverture.

Revue : au minimum une revue indépendante ciblée du delta (rescan, projections, graphe d'imports) avant toute publication.

## 11. Compatibilité historique

Aucun **module de production** existant n'est modifié par la tranche N2-a. B2, B3 v2-v6, B4, B5, E3-A, L3-A et la garde de préconditions gardent leurs identités, leurs digests et leur comportement. Les A0 formats 1 et 2 restent lisibles. Les résultats d'audit v4/v5 antérieurs ne sont ni réécrits ni requalifiés. Le protocole **ajoute** un module et ses tests.

**Un test historique doit toutefois être amendé** (correction issue de la revue indépendante) : `tests/test_gate_v_exposure_interpreters_v6.py`, `test_only_b5_and_nothing_else_imports_or_calls_v6` (≈ lignes 415-429) impose `importers == {"gate_v_exposure_store.py"}` et **aucun** appelant de `interpret_audit_roots_v6` ; le protocole importe et appelle v6, donc ce test échouerait. L'amendement conserve l'intention (« v6 n'est sélectionné par aucun consommateur historique ») en admettant exactement un importeur/appelant de plus, `gate_v_audit_protocol.py`. C'est une modification d'un test déjà publié : elle relève d'une décision de l'utilisateur (D11), de la même manière que les cinq assertions historiques actualisées par N-VIDE-1. Un futur écrivain E3-J qui accepterait autre chose qu'un rapport relancé par le protocole violerait AT-12 côté écrivain (test à écrire avec E3-J).

## 12. Validation restante de la publication précédente (limites documentées, hors périmètre de N-VIDE-2)

| Limite | Fait mesuré | Statut |
|---|---|---|
| 13 erreurs de l'arbre B isolé | `FileNotFoundError` sur `nasdaq_3m.csv` (fichier ignoré par Git) ; cause localisée : fixtures **module-scoped** de `tests/test_engine.py` (lignes 16-30, `load_data` sans garde ; 13 tests en dépendent) qui *errorent* à l'installation, alors que `tests/test_market_data_resample.py:255` *skippe* proprement | non corrigé |
| 76 tests ciblés ensuite réussis | `test_engine.py` + `test_market_data_resample.py` avec le CSV fourni | acquis |
| Pas de nouvelle suite complète sur cet arbre après restitution du fichier | la suite complète de l'arbre de travail (7882 passés, 63 ignorés) a été exécutée ; l'arbre B extrait n'a pas été rejoué en entier | **non fait** |
| POSIX / FIFO / liens symboliques non démontrés | `WinError 1314` ; 63 ignorés au lieu de 48 ; `HEAD` seul en ignore déjà 62 | **non démontré** |
| `MemoryError` historique | un cas, non reproduit, cause environnementale probable mais non démontrée | **non expliqué** |

**Proposition de validation Linux reproductible (sans nouveau code de production).**
1. Cible : le SHA publié `1ffa80f…` extrait par `git archive` dans un répertoire neuf (pas l'arbre de travail), Python 3.13 (version locale : 3.13.7), environnement virtuel neuf.
2. Dépendances : `requirements.txt` (ligne 9) contient `metatrader5==5.0.5735`, paquet **Windows seulement** ; `requirements-server.txt` existe déjà et ne le contient pas (à comparer avec `requirements.txt` avant de le choisir). Aucun fichier de `tests/` n'importe `metatrader5` (revue indépendante) : l'exclusion n'enlève aucun test.
3. Exécution : `pytest -q -rs -p no:cacheprovider` en groupes (B2/D8, B3, B5, L1/L2, L3-A, B4/E3-A, reste), puis suite complète ; `-rs` archivé pour comparer le total des ignorés à celui de Windows (63) et vérifier que les cas lien symbolique / FIFO / POSIX **s'exécutent** (les tests concurrents du Claim consomment ≈ 280 Mio de commit par worker : consigner pic de mémoire et limite du conteneur, sans skip ni retry ajoutés).
4. **Sans CSV privé** : deux sorties possibles, à choisir par l'utilisateur (D8) : (a) un mini-lot d'hygiène qui fait *skipper* proprement les fixtures de `test_engine.py` sans le CSV (marqueur `requires_private_data`) tout en gardant les tests synthétiques de ce fichier (à partir de la ligne 128) ; (b) un jeu synthétique minimal commité (taille et licence à vérifier). Aucune refonte des tests historiques n'est proposée.
5. Moyens : WSL est présent sur le poste (`C:\Windows\system32\wsl`, distribution et disque non vérifiés) ; Docker n'est pas dans le `PATH` (Rancher Desktop semble installé, non vérifié) ; le dépôt n'a **pas** de `.github/workflows` : un CI GitHub serait un acte sortant, soumis à décision (D8).

**Statut exact de la validation Linux après N2-a (2026-11-03) : NON EXÉCUTÉE, aucune preuve POSIX.** `wsl.exe` existe mais `wsl -l -v` répond « Le chemin d'accès spécifié est introuvable » (aucune distribution utilisable constatée) ; Docker est absent du `PATH` ; aucun `.github/workflows`. Le test de lien symbolique de N2-a (`test_a_symbolic_link_is_refused_where_the_platform_allows_creating_one`) est ignoré sur ce poste (`WinError 1314`), et le test de casse du nom réel (`test_the_real_name_on_disk_decides_attribution…`) ne s'exécute que sur un système de fichiers insensible à la casse. Rien n'est affirmé pour FIFO, liens symboliques et sémantique POSIX. Les 13 erreurs `nasdaq_3m.csv` de l'arbre B isolé de la publication précédente ne sont pas corrigées par N2-a (hors périmètre).

## 13. Frontières futures et ordre recommandé

| Lot | Obligation propre | Hors périmètre de N-VIDE-2 |
|---|---|---|
| **N-VIDE-2** | audit obligatoire fail-closed, rescan de protocole, appel de L3-A et du diagnostic, rapport typé | rescan indépendant au sens E3-J, chronologie, D5, S0, admission |
| **L3-B** | recalcul des faits S0 (trame, hash de source, fenêtre, snapshot, durée de barre) ; sorties **attendues** face au ValidationRun | conforme à `not_proven` (`S0_RECOMPUTATION`) |
| **E3-A** | éventuel `SourceKind` (`VALIDATION_RUN_PRE_HOLDOUT`, `…_DERIVED`), producteur d'`ABSENCE_ESTABLISHED`, nouvelle version d'inventaire | N-VIDE-2 n'ajoute aucun `SourceKind` |
| **E3-C** | publication réelle des preuves (couverture, sessions, sceau) par l'orchestrateur ; tant qu'aucun producteur n'existe, toute campagne avec Walk-Forward reste `INCOMPLETE` (comportement voulu) | — |
| **E3-J** | audit **indépendant** (processus/identité distincts), chronologie et preuve de temps, antériorité du sceau, D5, attestation, autorisation, écrivain RESERVATION/ADMISSION qui **relance** l'audit | — |
| **N-VIDE-3** | « un répertoire de sortie vide reste un squelette bloquant » : déjà vrai en v5/v6 ; **décision toujours ouverte**, supposée par AT-14 sans être décidée | — |

Dépendances : N-VIDE-2 N2-a n'a aucune dépendance ouverte (tout ce qu'il appelle existe). N2-b exige l'**adaptateur de lecture du registre** vers `RegistryView` / `AccountingViews` (aucun producteur n'existe) et la décision sur la dérivation de l'étage. L3-B est indépendant de N-VIDE-2 mais requis par E3-A (exclusion). E3-A dépend de L3-B et de N-VIDE-2. E3-J dépend de tout ce qui précède.

Ordre recommandé : **(1) cette conception acceptée → (2) N2-a (noyau : requête, S1, recevabilité, L3-A par racine, projections, S2, rapport ; pas de registre, pas de B4/B5) → (3) validation Linux, en parallèle et sans code → (4) N2-b (adaptateur de registre, B4, A0 pur) → (5) L3-B → (6) E3-A / E3-C → (7) E3-J.** Rien n'est implémenté par cette note.

## 14. Décisions nécessitant l'autorisation de l'utilisateur

| # | Décision | Recommandation |
|---|---|---|
| D1 | Créer `gate_v_audit_protocol` comme couture unique et verrouiller le graphe d'imports (AT-12) | oui |
| D2 | Plancher B3 = v6 par liste blanche explicite ; v4/v5 refusés à l'audit mais lisibles | oui |
| D3 | `RulesVersions.is_current()` reste lié à v4 (aucune activation globale) ; une activation éventuelle = décision distincte | oui, inchangé |
| D4 | Rescan de protocole : S2 frais, refus si `F` ou `I` diffèrent (y compris un simple `touch`) | oui (conservateur) ; alternative : ignorer `mtime` seul — rejetée |
| D5 | Fenêtre `W` dérivée du split plan persisté référencé par le plan V2 (chaîne de la section 4.1) ; tant que les chargeurs ne sont pas branchés, `W` configurée par l'opérateur et rapportée `OPERATOR_CONFIGURED` | oui |
| D6 | Rapport d'audit non persisté en N2 (pas de format A0 3, pas de fichier annexe, qui exigerait une nouvelle table B3) | oui ; persistance à décider avec E3-C / E3-J |
| D7 | Découpage N2-a (noyau) puis N2-b (registre, B4, A0) | oui — **tranche suivante recommandée : N2-a seule** |
| D8 | Validation Linux : moyen (WSL local, Docker, CI GitHub) et traitement du CSV privé (skip propre ou jeu synthétique) | WSL local d'abord ; skip propre dans un mini-lot séparé ; pas de CI sortant sans accord |
| D9 | Valeurs opérationnelles des plafonds (23.24) | laisser ouvert : le protocole les exige explicites et n'en invente aucune |
| D10 | N-VIDE-3 | laisser ouvert ; le comportement actuel est caractérisé par AT-14 |
| D11 | Amender `test_only_b5_and_nothing_else_imports_or_calls_v6` (admettre `gate_v_audit_protocol.py`, intention conservée) — seul test historique touché par N2-a | oui, avec N2-a |
| D12 | Différer `publish_audit_a0` et décider séparément du gating de B6 sur `rules_versions` (B6 charge tout A0 sans contrôle de version) | différer ; ne pas publier d'A0 d'audit avant cette décision |
| D13 | Vérification de relecture d'un A0 avant écriture : exposer une fonction publique dans B5 (amendement) ou importer un nom privé | décision en N2-b ; ne rien amender en N2-a |

## 15. Menaces résiduelles

- **T1** Modification après S2 (ou restaurée à l'identique entre S1 et S2) : non détectée ; seul E3-J, avec chronologie, peut la traiter.
- **T2** `ExposureScan` / `ExposureInventory` / `OwnCampaignContext` forgés par du code du même processus : le protocole ne peut pas les distinguer d'objets réels ; mitigation par signature, graphe d'imports et ré-exécution, pas par cryptographie.
- **T3** Chaîne L2 cohérente écrite a posteriori : indétectable sans preuve de temps (`SEAL_ANTERIORITY`).
- **T4** Relabelling v5 ↔ v6 d'un A0 : non détectable (même digest) ; neutralisé en ne traitant jamais un A0 comme attestation.
- **T5** Résolution grossière de `mtime`, systèmes de fichiers réseau, horloge : l'identité `I` est un indice, pas une garantie.
- **T6** Lecture réelle du DataFrame par un worker, exclusivité des sources, durabilité : hors de portée de tout audit de fichiers (`NOT_PROVEN`).
- **T7** Divergence future des tables v5 et v6 : L3-A figé sur v5 (`TABLE_VERSION`) ; contrôle à l'exécution, mais L3-A devra recevoir une version.
- **T8** Absence d'adaptateur de registre : N2-b dépend d'un composant E3-D non existant ; l'audit « de bout en bout » n'est pas livrable avant lui.
- **T9** Coût de rescan : deux interprétations complètes ; borné par `scan_worst_case_read_bytes` ×2 par disposition, à budgéter (D9).
- **T10** Un rapport mal lu comme un laissez-passer : mitigé par le vocabulaire fermé, `grants == ()`, `e3j_prerequisites_unmet` non vide, mais reste un risque de lecture humaine.
- **T11** Cas Windows (liens, FIFO, jonctions) non démontrés tant que la validation Linux (section 12) n'est pas faite.
- **T12** Voie de lecture B6 : tout A0 de `exposure/` (v4 historique comme v6) est chargé sans contrôle de version ; l'audit obligatoire ne couvre pas cette voie (D12).
- **T13** *(supprimée : la couture privée `_audit` n'existe plus ; les refus défensifs sont testés par `mock.patch` du nom `interpret_audit_roots_v6`.)*
- **T14** `window_provenance = UNVERIFIED` : tant que `W` n'est pas dérivée du split plan persisté, le protocole ne peut pas détecter une `W` erronée.
- **T15** (ajoutée par la revue du code N2-a) `gate_v_k1s2_verifier._cited_hashes` (L3-A, non modifié) construit l'ensemble des suites hexadécimales de 64 caractères et plus du `validation_run.json` avant tout contrôle de forme : une suite de runs hexadécimaux séparés par des espaces dans un fichier d'environ 3,9 Mio a été mesurée à environ 470 Mio de pic mémoire et 7,6 s. Le protocole ne peut pas la borner sans modifier L3-A ; la borne effective est `ScanLimits.max_json_bytes` (configuration de l'opérateur) et `MAX_CONTENT_BYTES` de L3-A (4 Mio). À traiter par un durcissement de L3-A (plafond du nombre de candidats), hors N2-a.
- **T16** Un `AuditReport` est forgeable par `object.__new__` ou `dataclasses.replace` (efface blocages et racines) : le rapport n'a aucun consommateur et aucun pouvoir ; seule la ré-exécution par l'aval protège (limite de protocole, comme T2).

## 16. Skills et outils utilisés pour cette note

Invoqués : `development-orchestrator` (obligatoire par le `CLAUDE.md` du dépôt), `codebase-design` (vocabulaire module / interface / couture / profondeur ; test de la suppression), `domain-modeling` (vocabulaire des statuts ; **aucune mise à jour de `CONTEXT.md`**, qui porte des modifications étrangères), `caveman` (hook de session). **Non invoqués** : `to-spec` (publie dans les GitHub Issues : sortant, contraire à « une seule note, aucun push »), Spec Kit (dépôt non initialisé), `code-review` projet (aucun diff de code), Playwright / UI (aucune interface), `/codex-orchestrator` et autopilote (interdits). Revue indépendante ciblée : voir l'addendum ci-dessous.

## 17. Addendum — revue indépendante ciblée (2026-11-03)

Relecteur unique, agent `general-purpose`, contexte neuf, **lecture seule**, ≈ 10 min, vérification contre le code (HEAD `1ffa80f`). Il n'y a pas de second relecteur et le delta de correction ci-dessous n'a **pas** été relu par un second relecteur indépendant (vérification interne).

**Résultat : 1 HIGH, 8 MEDIUM, 8 LOW/MEDIUM-LOW ; tous traités dans cette note.** Cinq findings ont été revérifiés personnellement contre le code avant correction (#1, #2, #7, #8, #15) et se sont confirmés.

| # | Sévérité | Défaut | Correction |
|---|---|---|---|
| 1 | HIGH | `W` n'est pas un champ du plan V2 (`GateVCampaignPlanV2` : 27 champs, aucune fenêtre) ; elle est dans le `DatasetSplitPlan.final_holdout` référencé par `split_plan_id` | §4.1, §6 (`window_provenance`), D5, T14 |
| 2 | MEDIUM | `scan.hash_limits == requête` refuserait `RESULTS` et `SPLIT_PLAN_DIR` (B3 pose `None` pour les tables non hachées) ; `HASH_LIMITS_MISSING` mal formulé | §4.4, §4.8, §8 |
| 3 | MEDIUM | `F`/`I` plus stricts que `_comparable` de B2 (fichiers inertes, journaux vivants) | §4.13 : périmètre aligné sur B2 |
| 4 | MEDIUM | refus et statuts incohérents (refus ⇒ aucun fait, mais cas attendant refus + statuts) | séparation refus (R) / blocages (B), §4.5, §6, §8 |
| 5 | MEDIUM | `inventory` `NOT_BUILT` en N2-a mais attendu `COMPLETE` ; `complete` de B4 ≠ B3 | `b3_completeness` + `inventory_b4`, §6 |
| 6 | MEDIUM | le seul rapport « complet » est un rapport « rien observé » ; cas 1 et 19 indiscernables ; clause AT-04 vide | `manifest_state`, `observed_execution_artefacts`, cas 19 précisé, AT-04 par mutation de constantes |
| 7 | MEDIUM | un test historique (`only_b5_…imports_or_calls_v6`) échouerait | §11, AT-12/13, D11 |
| 8 | MEDIUM | B6 charge tout A0 sans contrôle de version ; `is_current()` sans appelant de production | §2, §4.11, §5.5, T12, D12 (`publish_audit_a0` différé) |
| 9 | MEDIUM | `campaign_id` unique ferait refuser les campagnes dérivées | `own_campaign_id` + `expected_name` par racine, §3, §4.3, cas 17 |
| 10 | LOW/MED | `WRONG_TABLE` inatteignable via l'adaptateur | §4.8 |
| 11 | LOW/MED | déclencheur de `verify_run_chain` ambigu (second run, run étranger) | §4.6 |
| 12 | LOW/MED | refus inatteignables par l'API publique ; espion AT-02 sur le mauvais module ; cas 13 trop fort | couture privée `_audit`, classe P/D, AT-02, cas 10-13, T13 |
| 13 | LOW | cas 3 : « aucun finding » faux avec le vrai producteur D2 | deux scénarios (a)/(b) |
| 14 | LOW | codes réels `MANIFEST_RUN_ABSENT` / `MANIFEST_RUN_EVIDENCE_MISSING` au format `CODE:…#ref` ; nom de fichier du cas 10 | §9 |
| 15 | LOW | vocabulaire interdit : le test de L3-A est un test de sous-chaînes sur les valeurs d'énumération ; `REQUEST_INVALID` contient `VALID`, `SCAN_HOOKS_PRESENT` contient `OK`, `exclusion_proof` contient `EXCLUSION`, les prérequis contiennent `ADMISSION` / `AUTHORI` | §6 : sous-chaînes + jetons, champ renommé `absence_evidence`, exemption figée |
| 16 | LOW | « refuser tout A0 que B5 refuserait » : relecture schéma + identités privée dans B5 | §4.11, D13 |
| 17 | LOW | `BaseException` ; budget ×2 par disposition ; formulation « seul B4 construit les vues » ; nom du chargeur B6 ; `requirements-server.txt` ; aucun test n'importe `metatrader5` ; ligne 128 de `test_engine.py` | §2, §4.4, §4.12, §12 |

**Affirmations vérifiées exactes par le relecteur** : aucun appelant de production de v6, B4, des préconditions et de L3-A ; aucun écrivain RESERVATION/ADMISSION ; `ExposureScan` constructible sans jeton ; digests v5 = v6 = `TABLE_DIGEST` ; `scan_audit_roots` appelé une fois par groupe de disposition et par interprétation (donc exactement deux fois pour S1 + S2) ; contrôles de `observed_tree_from_scan` ; `ready_vs_revision` vu par v6 seulement ; `inventory_id` inclut `complete` ; chiffres de la section 12 cohérents avec `AI_HANDOFF.md` §82.6 ; `.github/` absent ; Python 3.13.7. **Interdits de la mission** : aucun dépassement direct ; les deux points indirects relevés (publication d'A0, amendement d'un test historique) sont devenus les décisions D12 et D11.

## 18. Addendum — seconde revue de conception (gate N2-a, 2026-11-03) et périmètre normatif de N2-a

Seconde revue indépendante (agent `general-purpose`, lecture seule, ≈ 6 min, 42 appels d'outils) du document de 371 lignes, vérifiée contre le code. **Contradiction architecturale substantielle : NON** ; aucun HIGH. Huit écarts locaux, tous corrigés ; les deux premiers l'ont aussi été en ligne (§3, §4.1, §6). Les corrections ne sont revérifiées que par la revue du code final (voir §19).

| # | Sévérité | Écart | Décision pour N2-a |
|---|---|---|---|
| 1 | MEDIUM (condition normative) | `canonical_bytes()` / `report_digest` publics et flux AuditReport vers E3-J : rapport transportable | retirés ; aucune méthode `to_*`, `from_*`, `canonical_*`, `__reduce__` ; test AST |
| 2 | MEDIUM (condition normative) | `PLAN_AND_SPLIT_LOADED` sur-déclarait ; les chargeurs ne sont pas appelables avec deux chemins | `window_provenance = UNVERIFIED` seule ; chargeurs et `WINDOW_MISMATCH` hors N2-a |
| 3 | MEDIUM | `test_v5_is_never_activated_silently…` (`test_gate_v_exposure_v4_v5_differential.py`) échouerait si le module contenait les sous-chaînes de nom du module B3 v5 ou de sa fonction d'interprétation | le module ne contient jamais ces sous-chaînes (liste blanche littérale « …_v6 », v4 et v5 jamais nommés) ; test de garde dédié ; aucun second test historique touché |
| 4 | MEDIUM | dérivation de `manifest_state` non spécifiée | lue sur `ObservedItem.content` de `manifest.json` (jamais `observation.value`) : item absent donne `ABSENT` ; raisons `MANIFEST_UNREADABLE`, `MANIFEST_NOT_CONFORMING`, `FOREIGN_MANIFEST` du diagnostic donnent `UNREADABLE_OR_NONCONFORMING` ou `FOREIGN` ; sinon `status` du record (`READY_FOR_EXECUTION` devient `INITIAL`, `EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT` devient `EVIDENCE_COMPLETE`, les autres identiques) ; aucun import privé de B3 |
| 5 | LOW/MEDIUM | la couture privée `_audit(…, _interpreter)` est un vecteur de forge ; la garde « nul ne référence `_audit` » est fragile | supprimée : le protocole appelle `interpret_audit_roots_v6` par un nom de module et les tests le remplacent par `monkeypatch` (le faux enveloppe le vrai v6) ; `RESCAN_NOT_DISTINCT` par identité d'objet de l'interprétation et des scans ; T13 disparaît |
| 6 | LOW | `I` omet l'identité des racines ; fenêtre et (disposition, labels, chemins) non confrontés à la requête | racines (`label`, `path`, `st_dev`, `st_ino`, `may_be_empty`) et fenêtre dans `I` ; confrontation à la requête : `ROOT_FOREIGN` (racines) ou `SCAN_CONTEXT_MISMATCH` (fenêtre) |
| 7 | LOW | `OBSERVATION_REFUSED` refuse tout l'audit (L3-A impose `gate_v_v2_<64 hex>`) ; aucune racine propre ; champs `registry_root` / `historical_a0_hashes` inutiles ; `HashLimits` incohérent inconstructible | refus global assumé (conservateur) ; `REQUEST_INVALID` pour l'absence de racine propre ; champs retirés de `AuditRequest` ; les tests forgent les objets de limites par `object.__new__` |
| 8 | LOW | AT-12 : imports directs seulement | v6 charge transitivement le Claim, le plan V2, `dataset_split` et pandas ; la règle porte sur les imports directs du module et sur l'absence de B4, B5, registre et préconditions dans `sys.modules` après son import |

**Périmètre normatif N2-a (approuvé par l'utilisateur dans le mandat)** : requête de configuration stricte, S1 par B3 v6, vérification L3-A par run Walk-Forward concerné, diagnostic des répertoires vides, projections F (faits) et I (identité et contexte), S2 par un second appel frais, rapport sans pouvoir d'autorisation, amendement ciblé D11. **Non acceptés** : N2-b, N2-c, D12/D13 opérationnels, N-VIDE-3, L3-B, E3-J, l'ensemble de D1 à D13, R9. Le rapport de N2-a ne porte pas `inventory_b4` (B4 non appelé) et ne persiste aucun A0.

## 19. Mise en œuvre de N2-a et gate d'acceptation (2026-11-03) — état réel

**Statut : N2-a IMPLÉMENTÉ ET TESTÉ LOCALEMENT, NON COMMITÉ, NON POUSSÉ.** Verdict du gate d'acceptation : `N2-a ACCEPTANCE GATE PASSED — READY FOR PUBLICATION APPROVAL`. La publication elle-même (commit, push) n'est pas autorisée par cette note et reste une décision de l'utilisateur. Le reste de N-VIDE-2 (N2-b, N2-c, D12 et D13 opérationnels, N-VIDE-3, L3-B, E3-J) et l'ensemble de D1 à D13 restent **PROPOSED** ; R9 reste PROPOSED globalement. `REAL` = DISABLED / NOT QUALIFIED · `GATE V` = NON PASSÉE · `FINAL_HOLDOUT` = NON ACCÉDÉ. Aucune admission, aucun Claim, aucun A0, aucun verdict scientifique nouveau.

### 19.1 Contenu livré (checkpoint `1ffa80f422af64bc52e70eef4679030a5af360e3`, divergence 0/0 avec `origin/master`)
- Nouveaux fichiers non suivis : `gate_v_audit_protocol.py` (684 lignes) ; `tests/test_gate_v_audit_protocol_{scenarios,request,rescan,invariants}.py` ; `tests/gate_v_audit_protocol_support.py`.
- Seul fichier suivi modifié : `tests/test_gate_v_exposure_interpreters_v6.py` (+25 / −3) : garde D11. Aucun module de production existant n'est modifié ; `RulesVersions.is_current()` reste lié à v4 ; L3-A, B2, B3, B4, B5 et E3-A sont inchangés.
- Index réel inchangé : empreintes `1abfc53f…` (`diff --cached --raw --no-abbrev`) et `8b78a333…` (`diff --cached --binary`) reproduites avant et après le gate. Travaux étrangers, `=1.12.0`, `CONTEXT.md`, `AI_HANDOFF.md` (non modifié par ce lot), ADR locaux et `app_corrupted_backup.py` préservés.
- Contrat implémenté (voir §3, §6 et §18 pour les écarts à la conception initiale) : `audit_campaign_exposure(AuditRequest) -> AuditReport`, fonction totale et sans écriture ; 18 codes de refus ; blocages `CHAIN_INCOHERENT` et `EMPTINESS_BLOCKING` ; `window_provenance = UNVERIFIED` ; aucun plafond par défaut ; rapport ni sérialisable ni copiable. Statuts de vocabulaire fermé, aucune valeur `FRESH`, `NO_OVERLAP`, d'autorisation, d'accès au holdout ni de passage de la Gate V.

### 19.2 Résultats du gate (mesurés)
| Contrôle | Résultat |
|---|---|
| Tests N2-a (4 fichiers) | 154 passés, 1 ignoré (lien symbolique, `WinError 1314`) |
| Régressions B3 v4 / v5 / v6, différentiel v4-v5, L3-A (observations, vide, vérificateur, fuzz) | 841 passés, 4 ignorés |
| Quatre tests EODHD du précédent échec | 4 passés avec 7,16 Gio libres (voir 19.3) |
| Suite générale, code définitif | **8039 passés, 64 ignorés, 0 échec, 0 erreur, code de sortie 0, 25 min 17 s** ; disque 6,363 Gio avant, 4,557 Gio après |
Le détail des 64 ignorés n'a pas été capturé dans ce rejeu (options `-rs` et `-rf` combinées, aucune ligne `SKIPPED` écrite) ; le total est identique à celui du rejeu précédent (64). Les ignorés incluent les cas de liens symboliques, FIFO et POSIX de ce poste Windows.

### 19.3 Les quatre tests EODHD
Échec du rejeu précédent : `EodhdStorageError: Espace disque insuffisant … minimum requis 2048 Mo` (1,35 Gio libres au moment de la suite, 1,05 Gio au rejeu). Cause : la garde disque d'EODHD, sans lien avec N2-a (ces tests n'importent pas le protocole). Rejeu avec 7,16 Gio libres : tous passent, sans contournement de `EodhdStorageError`, sans désactivation de la garde, sans ignorés artificiels. Noms exacts et fichiers (correction du compte annoncé : deux dans chaque fichier, non un et trois) : `test_ui_data_center.py::test_build_eodhd_catalog_rows_lists_stored_snapshots` et `::test_build_unified_catalog_rows_combines_local_and_eodhd` ; `test_unified_catalog.py::test_build_unified_catalog_with_only_eodhd_source` et `::test_build_unified_catalog_combines_both_sources`. Ces tests dépendent de l'espace disque libre de l'hôte : ils échouent à nouveau sous 2 Gio, ce qui est le comportement voulu de la garde.

### 19.4 Garde D11 (importation de B3 v6)
Sonde exécutée sur le dépôt entier avec la fonction de la garde amendée : importeurs de `gate_v_exposure_interpreters_v6` = `{gate_v_audit_protocol.py, gate_v_exposure_store.py}` ; appelants de `interpret_audit_roots_v6` = `{gate_v_audit_protocol.py}`. L'autorisation est nominative (égalité exacte de deux noms de fichier) ; un test négatif prouve qu'un troisième consommateur ou un nom voisin sort de l'ensemble autorisé. Le module du protocole ne contient jamais les sous-chaînes de nom de B3 v4 ou v5 (garde du test historique de non-activation silencieuse de v5, également vert). Limite historique, non introduite par l'amendement : le contrôle est une recherche de sous-chaîne et reste contournable par un import dynamique.

### 19.5 Mutations
Harnais jetable (copie de l'arbre, production jamais touchée), une seule instance à la fois : 68 mutants exécutés (campagne initiale de 58, extension à 67, plus 2 variantes de la projection de l'arbre) ; 66 tués après ajout de tests dictés par les survivants (hash de contenu isolé, findings seuls, raisons seules, `rule_tag`, anomalie seule, taille d'un fichier haché anormal, identité de racine, digest de table par disposition, taille seule dans la conversion). Les 2 survivants restants sont **équivalents, démontrés par une sonde reproductible** (énumération exhaustive des états constructibles de `ScanObservation` : 208 états, aucune ambiguïté dès que `(entry_class, anomaly)` sont connus ; `EntryKind` n'a que `FILE` et `DIRECTORY`) : retirer `kind` ou `value_parsed` de la projection F ne change donc jamais le résultat, car les invariants du constructeur les déterminent. Limite : l'équivalence vaut pour les états que le constructeur accepte aujourd'hui ; si ses invariants changent, la sonde doit être rejouée.

### 19.6 Risques résiduels : T15 et T16
- **T15 (mémoire de L3-A, mesuré).** `_cited_hashes` n'est appelé que sur le `validation_run.json` du run attendu de chaque racine, une fois par racine. Avec un fichier JSON valide adverse de 3,9 Mo (suites hexadécimales de 256 caractères séparées par des espaces) : pic de 460 Mo pour une racine et de 467 Mo pour trois racines, mémoire retenue nulle après l'audit. Le pic est donc un **maximum par fichier, non une somme par racine** (la mémoire est libérée entre deux racines) ; le temps croît linéairement (≈ 12 s par racine avec tracemalloc). Borne dure : `MAX_CONTENT_BYTES` de L3-A (4 Mio), soit un pic d'environ 0,5 Go. **Aucun dépassement non maîtrisé démontré, risque non bloquant.** Correctif minimal proposé (non appliqué, hors périmètre, nécessite de modifier L3-A) : plafonner le nombre de suites hexadécimales candidates dans `_cited_hashes` et traiter le dépassement comme `overlong`.
- **T16.** Un `AuditReport` reste forgeable par `object.__new__` dans le même processus ; sans consommateur ni pouvoir, seule la ré-exécution par l'aval protège. `RootReport`, `AuditBlock` et `AuditDefect` restent sérialisables : sans autorité propre.
- T1 à T12 et T14 (§15) restent valides. T13 est supprimée.

### 19.7 Limites Linux / POSIX et historique
Aucune validation Linux n'a été exécutée : `wsl.exe` existe mais sans distribution utilisable, Docker absent, pas de CI. Aucune preuve POSIX, FIFO ou liens symboliques n'est apportée ; le test de lien symbolique de N2-a est ignoré ici ; le test de casse du nom réel ne s'exécute que sur un système de fichiers insensible à la casse. Les 13 erreurs `nasdaq_3m.csv` de l'arbre B isolé de la publication précédente ne sont pas corrigées et n'ont pas été rejouées : le CSV est présent dans cet arbre de travail, la suite complète y est verte, mais cela ne prouve rien pour une extraction sans ce fichier.

### 19.8 Prérequis de N2-b (non accepté, PROPOSED)
- Un adaptateur de lecture du registre vers `RegistryView` et `AccountingViews` (aucun producteur n'existe), avec lecture stricte de la chaîne et vérification de la tête de chaîne en fin d'audit.
- Dérivation de l'étage des enregistrements propres depuis le registre relu (jamais fournie) et paramètre `derived_root_labels` de B4.
- Décision D13 (vérification de relecture d'un A0 : fonction publique de B5 ou import d'un nom privé) et D12 (gating de B6 sur `rules_versions`) avant toute publication d'A0 par l'audit.
- Chargeurs du plan V2 et du split plan avec `validate_…_sources` pour que `W` cesse d'être `UNVERIFIED` (chaîne : plan V2 → `split_plan_id` et empreinte → split plan → `final_holdout`).
- Si le durcissement de T15 est voulu, une modification de L3-A distincte et revue séparément.

### 19.9 Compétences et revues
Invoqués : `development-orchestrator` (à chaque message), `tdd` (méthode : tests puis code ; le rouge initial du premier lot n'a pas été capturé en exécution, le rouge des huit correctifs post-revue l'a été), `codebase-design`, `domain-modeling`, `caveman` (hook) ; deux relecteurs indépendants `general-purpose` en lecture seule (conception, puis code final avec revérification des corrections). Aucun correctif fonctionnel n'a été nécessaire lors de ce gate : pas de nouvelle revue. Non invoqués : `to-spec`, Spec Kit, `code-review` du projet, Playwright, `/codex-orchestrator`, autopilote.
