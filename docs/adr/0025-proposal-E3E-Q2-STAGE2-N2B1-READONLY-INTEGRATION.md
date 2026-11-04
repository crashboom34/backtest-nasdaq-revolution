# E3-E — K1 Étape 2, N-VIDE-2 / N2-b1 : intégration en lecture seule (provenance de W, registre, B4) — note de CONCEPTION, PROPOSED — READY FOR USER REVIEW

**Statut après le gate de publication (2026-11-04).** La tranche **N2-b1a seule** (provenance de W : `gate_v_audit_window.py`, extension de `gate_v_audit_protocol.py`, tests) est **publiée**, après une revue indépendante finale du delta (ECC `security-reviewer`, lecture seule, verdict `FINAL DELTA REVIEW PASS`, aucun défaut HIGH ni MEDIUM, quatre LOW consignés en 18.6) et sans changement fonctionnel depuis le code testé (SHA-256 relevés et identiques). `SPLIT_PLAN_FINGERPRINT_MATCHED` reste une cohérence de métadonnées, jamais une authenticité. **N2-b1b, N2-b2, N2-c, N-VIDE-2 pris globalement, D12, D13, L3-B et E3-J restent PROPOSED et non implémentés**, et tout ce qui est écrit ci-dessous hors de la section 18 reste une conception non normative. Le paragraphe suivant décrit l'état de la note avant ce gate.

**Statut (2026-11-03).** Conception seule, **locale, non commitée, non normative** (avant l'implémentation N2-b1a et son gate). Aucun code, aucun test, aucun commit, aucun push. Checkpoint : `c97e394e4aaac38187cacf2dfaaa4ee729eef487` (= `origin/master`, divergence 0/0 après `git fetch`). N2-a est publié et accepté **dans son périmètre technique seulement** (`gate_v_audit_protocol.py`, garde D11). Tout ce qui suit est **PROPOSED** : N2-b1, N2-b2, N2-c, N-VIDE-2 global, D12, D13, R9 et D1 à D13 de la note N-VIDE-2. Chaque décision de la section 13 attend l'autorisation explicite de l'utilisateur. Aucun amendement de l'ADR 0025, d'E3-A, de B2 / B3 / B4 / B5 / B6, de L3-A, du registre E3-D ni de N2-a n'est opéré par cette note.
`REAL` = DISABLED / NOT QUALIFIED · `GATE V` = NON PASSÉE · `FINAL_HOLDOUT` = NON ACCÉDÉ. Aucun A0, aucune admission, aucun Claim, aucun `SourceKind` nouveau, aucun L3-B, DERIVED ou E3-J.

Documents liés : `docs/adr/0025-proposal-E3E-Q2-STAGE2-NVIDE2-AUDIT-PROTOCOL.md` (N2-a, §§4.10, 4.11, 13, 14, 19.8), `AI_HANDOFF.md` §83.

## 1. Sources lues et préchecks

| Source | Ce qui en est retenu (lu, pas supposé) |
|---|---|
| `gate_v_audit_protocol.py` (N2-a) | point d'entrée unique `audit_campaign_exposure`, `_audit` privé non paramétré ; S1 puis S2 via le nom de module `interpret_audit_roots_v6` ; `AuditRequest` à 8 champs figés par un test ; `AuditReport` avec `b4_inventory` **propriété constante** `NOT_BUILT` ; refus et blocs en vocabulaire fermé |
| `gate_v_exposure_inventory.py` (B4) | `assemble_exposure_inventory(interpretation, *, registry, accounting, own_context, derived_root_labels=())` ; vues injectées `RegistryView`, `AccountingViews` (5 vues optionnelles) ; **aucun producteur** hors tests ; `complete` de B4 = B3 complet ET registre sans anomalie ET une racine statique ; B4 « n'élargit jamais la complétude de B3 » |
| Registre E3-D : `gate_v_registry_store.py`, `_chain.py`, `_model.py`, `_views.py`, `_append.py` | `read_registry(root, *, barrier)` : lecture **stricte et complète**, mode `SYNTHETIC` seul (`REAL` ⇒ `MODE_REFUSED`), chaîne vérifiée (`verify_chain`), tout défaut lève (`RegistryReadError`, `RegistryChainError`), aucun résultat partiel ; types `RESERVATION`, `ADMISSION`, `CONSUMPTION`, `REBIND` ; un enregistrement de campagne porte `campaign_id`, fenêtre, `commitment_*`, `code_identity_hash`, **aucun** identifiant de `ResearchRun`, de stratégie, de clôture, d'ingestion ni d'engagement nul ; plafonds en dur du store : 100 000 slots de 256 Kio |
| Plan V2 et plan de split : `gate_v_campaign_plan_v2.py`, `dataset_split.py` | le plan V2 ne porte **aucune fenêtre** : `dataset_snapshot_id`, `split_plan_id`, `split_plan_fingerprint` ; `DatasetSplitPlan.final_holdout` est un `SplitBoundary(start, end)` demi-ouvert ; `load_gate_v_campaign_plan_v2(path)` est pur et **non fiable seul** (il exige `validate_…_sources`) ; `validate_gate_v_campaign_plan_v2_sources(plan, *, preregistration, research_run, split_plan, policy, policy_path, repo_dir=None)` ; `load_dataset_split_plan(path, *, strict=False)` (`strict=True` revalide par `build_dataset_split_plan`) ; `dataset_split_plan_fingerprint(plan)` = SHA-256 du JSON des métadonnées, « no market data is consulted » |
| E3-A (`gate_v_final_holdout_protocol.py`) | `OwnCampaignContext(current_campaign_id, own_record_stage)`, étage = **fait fourni** (« en production, E3-D et E3-J le dérivent ») ; étages `NO_OWN_RECORDS`, `RESERVED`, `ADMITTED`, `CLAIMED`, `CONSUMED` ; `CLAIMED` suppose un Claim **hors registre** (fichier de campagne) |
| B3 v6 | `plan.json` d'une campagne = `INFORMATIVE_JSON` (octets conservés) ; ancre : le `campaign_id` de `plan.json` doit égaler le nom du dossier ; `final_holdout_access_claim.json` = source exposante `FINAL_HOLDOUT_CLAIM` ; `interpretation.plans` (`PlanIndexEntry` : `split_plan_id`, empreinte, bornes) pour les racines `SPLIT_PLAN_DIR` |
| B5 / B6 | B5 : `build_exposure_inventory_record` pur, relecture de contrôle **privée** (`_prove_rereadable`, `_parse_record`) ; B6 `load_declaration_lineage` charge tout A0 de `exposure/` par `load_exposure_inventory` **sans contrôle de version** (`gate_v_exposure_declarations.py:871`) ; `RulesVersions.is_current()` sans appelant de production |
| `gate_v_inventory_preconditions.py` | garde pure ; consomme un inventaire et un contexte ; n'a **aucun appelant** hors tests |

Préchecks : branche `master`, HEAD = `origin/master`, divergence 0/0, index réel intact (empreintes `1abfc53f…` et `8b78a333…` reproduites), aucun verrou ni rebase ni merge en cours, travaux étrangers non touchés (`AGENTS.md` M, ADR 0016 A, `skills-usage.md` M indexés ; `AI_HANDOFF.md`, `CONTEXT.md`, ADR locaux, `api/`, `services/`, `frontend/`, `=1.12.0` non indexés), `app_corrupted_backup.py` non touché, 4,3 Gio libres, aucun téléchargement, aucun backtest.

## 2. Cartographie des producteurs et consommateurs (mesurée)

| Objet | Producteur réel | Consommateurs réels | Manque |
|---|---|---|---|
| `RegistryView` | **aucun** hors tests | B4 | adaptateur de lecture strict `RegistrySnapshot → RegistryView` |
| `RegistryRecordFact` | aucun | `RegistryView` | mapping des `ChainEntry` de type R / A / C ; `snapshot_id` : **absent du registre** ⇒ `None` |
| `ClosingView` (clôtures) | aucun ; le « `ClosingRecord` » n'est qu'un concept (ADR 23.27.5), aucune classe ni fichier | B4 (`abandoned_reservations`) | aucun artefact à lire |
| `TrialItemsView` (échecs d'ingestion, engagements nuls) | aucun | B4 | aucun artefact à lire |
| `CampaignTrialsView` (chaîne, V1 OOS) | aucun | B4 (`research_runs`, `strategies`) | attribution prouvée d'un `research_run_id` et de la configuration de stratégie évaluée à une campagne (contrat D1 de B4) ; non établie |
| `OwnCampaignContext` | aucun | B4, E3-A | dérivation de l'étage depuis le registre **et** le Claim de campagne |
| `derived_root_labels` | aucun | B4 | règle d'attribution des racines de campagnes de la chaîne |
| fenêtre `W` | l'opérateur (N2-a) | B3 v6, B4 | parcours plan V2 → split plan |
| A0 (record) | `build_exposure_inventory_record` (pur) | `publish_exposure_inventory`, B6 | **hors N2-b1** |

Conclusions : (1) **le registre ne contient pas la comptabilité des essais** : seules la liste des campagnes enregistrées et leurs fenêtres s'en déduisent ; les cinq autres compteurs de B4 n'ont aucune source lisible aujourd'hui. (2) Aucun producteur n'est « à migrer » : tout est à créer, en lecture seule. (3) L'étage `CLAIMED` et `CONSUMED` ne se déduit pas du registre seul. (4) Le registre n'a pas de paramètre de plafond : son coût de lecture est borné par des constantes du store (voir 5.2).

## 3. Architecture cible minimale

**Principe : aucun nouveau point d'entrée public.** `audit_campaign_exposure(AuditRequest) -> AuditReport` reste l'unique appel. N2-b1 ajoute **deux blocs de configuration optionnels** à la requête et des champs au rapport ; une requête sans ces blocs se comporte exactement comme N2-a (mêmes refus, mêmes statuts, `window_provenance = UNVERIFIED`, `inventory_b4 = NOT_BUILT`).

Deux modules profonds nouveaux, internes (jamais appelés hors du protocole), plus l'extension du protocole :
- `gate_v_audit_window.py` : `derive_window(plan_path, split_plan_path) -> DerivedWindow` ou refus typé (section 4). Lecture de **métadonnées uniquement**.
- `gate_v_audit_registry.py` : adaptateur de lecture du registre : `read_registry_facts(root, limits) -> RegistryFacts` (section 5) et constructions pures `build_views(...)` ; il **ne publie, ne re-confirme et n'ajoute rien**.
- `gate_v_audit_protocol.py` : orchestration (section 7).

Test de la suppression : sans ces modules, chaque futur appelant (E3-J) devrait réimplémenter la dérivation de `W`, la lecture stricte du registre, la dérivation de l'étage et des racines dérivées, et l'ordre des contrôles. Ils sont donc profonds ; l'interface reste une seule fonction.

**Frontières de confiance.** Digne de confiance : le code du dépôt, la configuration de l'opérateur. Non digne de confiance : tout contenu de disque (plan, split plan, registre, `plan.json` de campagne, Claim), même cohérent. **La cohérence d'un artefact ou d'une chaîne n'est jamais une preuve de provenance** (limite acceptée de la Décision 20.6 de l'ADR 0025 : une falsification totalement auto-cohérente n'est pas détectable par ce parcours).

## 4. Provenance de la fenêtre W

### 4.1 Parcours vérifiable et API réelles

0. **Garde de lecture préalable (obligatoire, avant chaque chargeur)** : `load_gate_v_campaign_plan_v2` et `load_dataset_split_plan` passent par `load_json_tolerant` : ils suivent les liens (`is_file`), lisent sans plafond de taille, acceptent une clé JSON dupliquée (la dernière gagne) et un FIFO POSIX peut les bloquer. Ces lectures échappent donc aux protections de B2. Le protocole fait avant chaque chargeur un `lstat` : fichier **régulier, non lien**, taille ≤ `limits.max_json_bytes`, sinon `WINDOW_SOURCE_INVALID` (ces refus précèdent ceux de B2, ce qui est dit sans détour). Les quatre lectures (plan et split plan, au chargement puis à la relecture finale) entrent dans le budget : `4 × max_json_bytes`. **L'autorité stricte reste S1** : la racine du split plan est une racine `SPLIT_PLAN_DIR` **configurée** (donc scannée en JSON strict par B2) et le contre-contrôle de l'étape 6 compare les objets chargés aux octets de S1 pour **les deux** fichiers ; une clé dupliquée ou un contenu que les chargeurs tolérants liraient autrement ne peut donc pas produire le niveau de provenance.
1. **Plan V2 persisté** : `load_gate_v_campaign_plan_v2(<racine propre>/plan.json)`. Chargeur pur, fail-closed ; vérifie structure, types et deux barrières internes (empreinte de protocole, puis `campaign_id`). Précondition : un fichier `plan.json` régulier. Il **ne prouve pas** la cohérence avec les sources externes.
2. **Contrôle contre les sources** : `validate_gate_v_campaign_plan_v2_sources` exige `GateVPreRegistration`, `ResearchRun`, `DatasetSplitPlan`, `GateVValidationPolicyVersion`, `policy_path` et, pour la provenance Git, `repo_dir`. Il appelle des commandes Git. **Il n'est pas dans N2-b1** (décision D-b1-2) : une requête qui ne donne que deux chemins ne peut pas l'appeler, et un sous-processus Git est une classe d'effet de bord que N2-a exclut (tests « ni horloge, ni réseau, ni sous-processus »).
3. **Identification du split plan exact** : le plan donne `split_plan_id`, `split_plan_fingerprint`, `dataset_snapshot_id`. Le fichier du split plan est **désigné par la configuration** (racine `SPLIT_PLAN_DIR` de la requête, fichier `split_plan.json`), jamais déduit d'un nom de dossier : le slug du plan est son identifiant, mais l'identité se prouve par le contenu.
4. **Lecture et validation du split plan** : `load_dataset_split_plan(path, strict=True)`. Elle retourne `None` si le fichier est absent, illisible ou de forme invalide, mais **lève `ValueError`** quand `strict=True` rejette une borne ou un identifiant (`build_split_boundary`, `build_dataset_split_plan`) : seuls `TypeError` et `KeyError` sont capturés par la fonction. L'adaptateur capture donc `ValueError` et `TypeError` autour des chargeurs **et** de `normalize_window` (qui refuse des formes que `build_split_boundary` accepte) et convertit tout en `WINDOW_SOURCE_INVALID` ; sans cela le résultat serait `AUDIT_INTERNAL_FAILURE`.
5. **Valeurs comparées, exactes** (égalité de chaînes après normalisation d'instant par `normalize_window`, jamais de comparaison lexicale d'instants) :
   - `plan.campaign_id` = nom de dossier attendu (`expected_name`) = `own_campaign_id` ;
   - `plan.split_plan_id` = `split.split_plan_id` ;
   - `plan.dataset_snapshot_id` = `split.dataset_snapshot_id` ;
   - `plan.split_plan_fingerprint` = `dataset_split_plan_fingerprint(split)` (recalculée, jamais lue) ;
   - `W` = `normalize_window(split.final_holdout.start, split.final_holdout.end)`.
6. **Contre-contrôle contre S1** (après le premier scan, sans relire le disque) : l'observation `plan.json` de la racine propre dans S1 (octets déjà conservés, JSON strict) doit porter les mêmes `campaign_id`, `split_plan_id`, `split_plan_fingerprint`, `dataset_snapshot_id` que le plan chargé avant S1 ; l'entrée `PlanIndexEntry` de la racine `SPLIT_PLAN_DIR` configurée doit avoir le même `split_plan_id`, la même empreinte et les mêmes bornes que le split plan chargé. Un écart signale un changement entre le chargement et S1.
7. **Relecture finale** : après S2, le plan et le split plan sont rechargés **avec la même garde de lecture (étape 0)** ; mêmes identifiants, même empreinte, même `W` ; sinon refus (`WINDOW_SOURCE_CHANGED`).
8. **Recoupement avec le registre** (section 5) : les fenêtres des enregistrements R / A / C de la campagne propre doivent égaler `W`.

Aucune donnée de marché n'est lue : `dataset_split_plan_fingerprint` ne consulte que les métadonnées du plan ; le chemin `holdout_access/` d'une racine `SPLIT_PLAN_DIR` n'est lu que par B3, comme en N2-a.

### 4.2 Ce que le rapport peut affirmer, par niveau

| Niveau `window_provenance` | Condition | Le rapport affirme | Le rapport n'affirme PAS |
|---|---|---|---|
| `UNVERIFIED` (N2-a, inchangé) | `W` fournie par l'opérateur | seulement l'origine déclarée | toute exactitude de `W` |
| `SPLIT_PLAN_FINGERPRINT_MATCHED` (nouveau, nom provisoire) | étapes 1, 3 à 8 réussies | `W` est la frontière `final_holdout` d'un `DatasetSplitPlan` dont l'identifiant, l'empreinte et le snapshot concordent avec le plan V2 chargé, et ces artefacts sont restés identiques pendant l'audit | que le plan V2 soit conforme à sa pré-enregistration, à sa `ResearchRun` ou à sa politique ; que les artefacts soient authentiques ou antérieurs ; que le snapshot corresponde à des données réelles |
| `PLAN_SOURCES_CROSS_VALIDATED` (**non livré**, tranche ultérieure) | étape 2 réussie avec les sources fournies | cohérence plan ↔ sources, y compris la provenance Git de la politique | l'authenticité de l'origine des sources elles-mêmes (une falsification auto-cohérente passe) |

Aucun niveau ne s'appelle ni n'implique « vérifié », « authentique » ou « établi ». Le champ `window_declared_source` du rapport vaut `OPERATOR_CONFIGURED` ou `SPLIT_PLAN_REFERENCED` (4.2, section 8).

### 4.3 Refus et contradictions (classe R, aucun statut de couche)

| Code | Condition |
|---|---|
| `WINDOW_SOURCE_INVALID` | plan V2 ou split plan illisible, absent, mal formé, ou racine de split plan non configurée ; `strict=True` refuse |
| `PLAN_SPLIT_CONTRADICTION` | un des quatre appariements de l'étape 5 échoue, ou le contre-contrôle de l'étape 6 échoue |
| `WINDOW_MISMATCH` | l'opérateur fournit aussi une fenêtre et elle diffère de celle dérivée ; ou une fenêtre de R / A / C de la campagne propre diffère de `W` |
| `WINDOW_SOURCE_CHANGED` | la relecture finale (étape 7) diffère |

Si la configuration ne demande pas la dérivation, la fenêtre de l'opérateur est la seule utilisée et le niveau reste `UNVERIFIED` : **jamais un repli silencieux** — une requête qui demande la dérivation et la rate est refusée, elle ne retombe pas sur la fenêtre de l'opérateur.

## 5. Registre et comptabilité

### 5.1 Lecture

`read_registry(root, barrier=True)` est appelé **deux fois** par le protocole (avant S1, après S2). Il est « lecture seule » au sens où il ne crée, ne modifie ni ne supprime aucun fichier, mais `barrier=True` fait un `fsync` du répertoire `admissions/` : ce n'est pas une opération sans appel système d'écriture, et sur un registre au profil `POSIX_DIR_FSYNC` lu sous Windows elle donne `BARRIER_FAILED` (refus `REGISTRY_UNREADABLE`). Le mode `REAL` est refusé par le store (`MODE_REFUSED`) ; un registre `SYNTHETIC` est lu sans valeur probante. Toute erreur du store (`RegistryReadError`, `RegistryChainError`) devient un refus typé `REGISTRY_UNREADABLE` portant le code d'origine ; **aucune vue partielle n'existe** : `RegistryView.unreadable_record_ids` est donc toujours vide en N2-b1 (la chaîne est lue en bloc ou refusée). Le contenu du registre n'est jamais dérivé d'un nom de fichier : `read_registry` impose l'égalité nom ↔ `seq`.

### 5.2 Budget de lecture (écart de conception à traiter)

Le store n'a pas de paramètre de plafond : bornes en dur de 100 000 slots de 262 144 octets, soit un pire cas de lecture de 24,4 Gio (26,2 Go), et la chaîne conserve jusqu'à 64 Kio de JSON par entrée en mémoire. N2-a exige des plafonds explicites. Proposition : `RegistryConfig.max_slots` explicite (sans défaut) ; **avant chaque** `read_registry` (R1 et R2), le protocole compte les entrées du répertoire `admissions/` par un listage borné (**c'est un accès disque**, hors de la « validation en mémoire ») et refuse (`RESOURCE_BUDGET_EXCEEDED`) au-delà ; le calcul `max_slots × 262 144 × 2` entre, lui, dans le budget total de `ProtocolLimits` avant tout accès. **Limite dite sans détour (TOCTOU)** : `read_registry` ne reçoit pas ce plafond et ne teste le sien qu'après un listage complet ; un ajout entre le comptage et la lecture n'est pas borné par `max_slots`, seulement par les constantes du store. Le contrôle est donc un garde-fou préalable, pas une garantie. Aucune modification du store.

### 5.3 Autorité de chaque champ

| Champ produit | Origine | Autorité |
|---|---|---|
| `RegistryView.registry_id` | `identity.json` du registre | lu ; `registry_id` de chaque slot égal à celui de l'identité (vérifié par la chaîne) |
| `RegistryView.chain_head` | `chain.head_content_hash` | **calculé** par la chaîne vérifiée ; valeur `hex64` (le genesis donne un hash défini) |
| `RegistryRecordFact.seq`, `kind`, `campaign_id`, `content_hash`, fenêtre | `ChainEntry` de type R / A / C | **lus et vérifiés** par la chaîne ; fenêtre normalisée par B4 |
| `RegistryRecordFact.snapshot_id` | néant dans le registre | `None` (jamais inventé) |
| entrées `REBIND` | `ChainEntry` sans campagne | **non converties en faits** ; comptées dans le rapport (`rebind_count`) ; elles changent l'instance en vigueur |
| `OwnCampaignContext.current_campaign_id` | `own_campaign_id` de la requête, déjà liée à un `expected_name` de dossier | déclaré par l'opérateur, contrôlé contre le plan V2 (4.1 étape 5) |
| `OwnCampaignContext.own_record_stage` | dérivé (5.4) | **dérivé**, jamais fourni |
| `derived_root_labels` | dérivé (5.5) | **dérivé**, jamais fourni |
| `AccountingViews` | néant exploitable (5.6) | vues absentes ⇒ `NOT_OBSERVED` |

Aucun de ces objets n'est un champ de `AuditRequest` ; les constructeurs de vues ne sont atteints que par l'adaptateur.

### 5.4 Étage des enregistrements propres

État du registre pour la campagne propre : `chain.campaign_state(own)` ∈ {`ABSENT`, `RESERVED`, `ADMITTED`, `CONSUMED`}. Présence du Claim : finding de type `FINAL_HOLDOUT_CLAIM` dans S1 dont le `source_id` désigne le fichier `final_holdout_access_claim.json` **de la racine propre** (forme `<TAG>:<label>/final_holdout_access_claim.json`, **à figer par un test de caractérisation**). Le `campaign_id` d'un Claim vient du contenu du fichier et vaut `None` s'il n'est pas résolu : l'attribution à la racine propre se fait donc par le `source_id`, jamais par ce champ ; un Claim non résolu dans la racine propre donne `STAGE_NOT_DERIVABLE`.

| Registre | Claim dans S1 | Étage |
|---|---|---|
| `ABSENT` | non | `NO_OWN_RECORDS` |
| `RESERVED` | non | `RESERVED` |
| `ADMITTED` | non | `ADMITTED` |
| `ADMITTED` | oui, un seul | `CLAIMED` |
| `CONSUMED` | oui, un seul | `CONSUMED` |
| tout autre cas | | refus `STAGE_NOT_DERIVABLE` (Claim sans admission ; consommation sans Claim ; plusieurs Claims ; Claim non résolu ou d'une autre campagne dans la racine propre) |

Un Claim présent mais non résolu est déjà une raison d'incomplétude de B3 ; le refus d'étage s'ajoute, il ne la remplace pas. Cette dérivation ne **classe** rien (E3-A) et n'appelle ni `partition_own_records` ni `classify_exposure`.

### 5.5 Racines dérivées

Une racine `CAMPAIGN_DIR` est **dérivée** si et seulement si : son `expected_name` est un `campaign_id` d'un enregistrement R / A / C de la chaîne **et** n'est pas la campagne propre **et** B3 n'émet, pour cette racine, ni `MISSING_REQUIRED:<label>/plan.json` (plan manquant) ni `INFORMATIVE_UNRESOLVED:<label>/plan.json` (`campaign_id` ≠ nom du dossier, ou anomalie de lecture) — **deux motifs exacts à figer par un test de caractérisation**. Toute autre racine de campagne reste **statique**. Règle conservatrice : en cas de doute, statique (jamais dérivée) ; l'attribution repose sur l'ancre `plan.json` déjà contrôlée par B3, donc sur un identifiant lu dans un fichier **et** confronté au nom du dossier — jamais sur le nom seul. Limite : le `campaign_id` de ce `plan.json` n'est pas re-dérivé de la pré-enregistration (Décision 20.6).

Couverture inverse : une campagne de la chaîne **sans** racine configurée est une source d'exposition non scannée. Le rapport l'expose (`chain_campaigns_without_root_count`, entier exact, et les 20 premiers identifiants triés ; la liste complète peut atteindre 100 000 entrées, donc n'est pas recopiée) et un blocage `DERIVED_COVERAGE_PARTIAL` (portée : absence) l'accompagne ; `AuditBlock.root_label` étant un texte obligatoire, la valeur sentinelle documentée `"(registry)"` est utilisée (aucune racine n'est en cause). B4 ne peut pas porter cette raison (son interface ne reçoit pas de raison supplémentaire) ; elle n'entre donc dans aucune formule d'identité d'E3-A.

### 5.6 Comptabilité des essais en N2-b1

`AccountingViews()` est construit **vide** (cinq vues `None`). Conséquences exactes dans B4 : `campaigns` est calculé depuis la seule chaîne (campagnes distinctes de R / A / C, campagne propre exclue) — `OBSERVED` ; `abandoned_reservations`, `failed_ingestion_attempts`, `void_commitments`, `research_runs`, `strategies` valent **0 avec la provenance `NOT_OBSERVED`**, jamais un zéro vérifié. Raisons : aucun artefact de clôture, d'ingestion échouée ou d'engagement nul n'existe ; l'attribution d'un `research_run_id` ou d'une configuration de stratégie à une campagne exige un lien d'artefact **prouvé** (contrat D1 de B4) que ni le plan V2 (qui porte `research_run_content_hash`, pas la preuve de ce qui a été évalué) ni la chaîne ne fournissent. La comptabilité de N2-b1 est donc **volontairement minimale** ; les vues chaîne et V1-OOS relèvent de N2-b2 (section 15).

Règles non négociables : (a) pas d'identité inventée ni déduite d'un nom ; (b) pas de déduplication par normalisation (B4 compare par égalité exacte) ; (c) deux évaluations distinctes ne doivent jamais partager un identifiant — non vérifiable ici, donc non fourni ; (d) valeurs observées et valeurs déclarées ne sont jamais fusionnées (question Q-3 de l'ADR 0025 reste ouverte) ; (e) campagnes étrangères : un enregistrement d'une autre campagne est un fait du registre (finding), jamais un essai ; (f) un compteur partiel ou non observé garde sa provenance et n'influence ni `complete` ni `inventory_id`.

## 6. Assemblage B4

Appel unique, en mémoire : `assemble_exposure_inventory(S1, registry=view, accounting=AccountingViews(), own_context=ctx, derived_root_labels=derived)`.

- **Placé après S1 et avant S2** (section 7) : B4 consomme les faits de S1, qui sont ceux que S2 va confronter.
- **Préservé** : les findings de B3 repris tels quels ; toutes les raisons de B3 conservées mot pour mot (B4 ne peut qu'élargir) ; `semantics_version` de B3 (`v6`) et de B4 (`gate_v_exposure_inventory_assembly_v1`) ; l'identité `inventory_id` d'E3-A (qui inclut `complete`) ; la provenance de comptabilité ; la séparation racines statiques / dérivées.
- **Complétudes distinctes** : `b3_completeness` (copie de B3) et `b4_completeness` = `assembly.inventory.complete`. Mesuré : avec une chaîne stricte, tous les enregistrements sont `RESOLVED` (campagne et fenêtre toujours présentes, `unreadable_record_ids` toujours vide) et la campagne propre est toujours une racine **statique** (5.5 l'exclut des racines dérivées et N2-a exige une racine propre) : `REASON_NO_STATIC_ROOT` et les raisons de registre sont donc **inatteignables par l'API publique**. **Invariants exacts de B4 (clarification demandée à la revue de N2-b1a ; elle remplace la formulation antérieure « invariant `b4_completeness == b3_completeness` »).** (i) B4 ne peut **pas** rendre complet un inventaire que B3 considère incomplet : toutes les raisons de B3 sont conservées mot pour mot. (ii) B4 **peut** ajouter des raisons d'incomplétude (`REASON_NO_STATIC_ROOT`, raisons issues du registre). (iii) L'égalité `b4_completeness == b3_completeness` n'est **pas** un invariant général : elle suppose l'absence de nouvelle raison d'incomplétude issue du registre **et** la présence d'une racine statique admissible. Avec l'adaptateur proposé (chaîne strictement lue, campagne propre toujours racine statique) ces deux conditions sont réalisées par construction ; le test d'égalité sur l'API publique de N2-b1b est donc un test de **non-régression conditionnel**, qui doit être réécrit si une raison de registre devient atteignable. Le cas « B3 complet, B4 incomplet » se teste au niveau de l'adaptateur avec une vue construite, jamais par l'API publique. (iv) **Comptabilité** : dimension distincte de la complétude de B4 ; les six compteurs gardent chacun leur provenance. Si seul `campaigns` est réellement observé, il porte `OBSERVED` ou `PARTIAL` selon la qualité de la lecture, et les cinq autres restent `NOT_OBSERVED` ; une valeur numérique 0 avec `NOT_OBSERVED` n'est **jamais** un zéro vérifié. N2-b1b, les racines dérivées, la dérivation de l'étage propre et les décisions de registre restent PROPOSED ; rien n'est implémenté dans B4.
- **Anomalies de registre** : une chaîne illisible ou rompue n'atteint jamais B4 (refus `REGISTRY_UNREADABLE`). Un changement de tête de chaîne entre les deux lectures est un refus `REGISTRY_CHAIN_HEAD_CHANGED` (aucun assemblage exposé).
- **Erreurs de B4 / E3-A** : un `ValueError` ou `TypeError` des constructeurs (listabilité, identités recalculées) devient un refus `B4_ASSEMBLY_REFUSED` ; jamais une exception.
- **Exposé par le rapport** : `b4_completeness`, `b4_incomplete_reasons` (raisons de B4 en plus de celles de B3, triées, intactes), `b4_semantics_version`, `inventory_id` (identité E3-A), `registry_id`, `registry_chain_head`, `rebind_count`, `accounting_provenance` (six valeurs), `derived_root_labels`, `chain_campaigns_without_root_count` et ses 20 premiers identifiants. **Non exposé** : l'objet `ExposureInventoryAssembly` lui-même, `inventory_content_digest`, tout A0, tout record persistable.
- `inventory_id` est une identité diagnostique : elle n'autorise rien, un consommateur doit relancer l'audit (principe de N2-a). Décision D-b1-9 sur son exposition.

Le résultat est un assemblage **en mémoire**, éphémère ; `persistence = NOT_PERSISTED` reste constant.

## 7. Intégration avec N2-a : séquence des vérifications

```
validation de requête (mémoire) : types, plafonds, budgets (scan + registre), blocs W et registre
 └ dérivation de W (si demandée) : plan V2 → split plan strict → comparaisons de 4.1       [lecture de 2 fichiers]
 └ registre R1 : listage borné → read_registry(barrier=True)                                 [refus typés]
 └ recoupement : fenêtres R/A/C de la campagne propre = W ; campagne propre ↔ plan V2
S1 = interpret_audit_roots_v6 (W) → recevabilité N2-a → contre-contrôle de plan (4.1.6) → L3-A par racine (N2-a)
 └ étage propre (5.4) ; racines dérivées (5.5) ; vues (5.3, 5.6)
 └ B4 : assemble_exposure_inventory(S1, …) → b4_completeness, identités
S2 = second appel frais (N2-a) → F / I (N2-a)
 └ relecture finale : registre R2 (barrier=True) → tête et chaîne identiques à R1 ; plan et split plan rechargés → identiques
rapport typé (aucun booléen global, aucune autorité)
```

**Pourquoi B4 avant S2 et les relectures finales après** : (1) B4 travaille sur S1 comme L3-A, donc sur le même jeu de faits ; (2) S2 confronte ce jeu ; (3) les relectures du registre et des sources de `W` encadrent **toute** la durée des deux scans et de B4, pour la fenêtre de détection la plus large. Les refus de N2-a (S1, S2, dérive F / I) gardent leurs codes ; les nouveaux contrôles s'insèrent sans modifier leur sémantique. **Exception dite sans détour** : les refus de la garde de lecture préalable (4.1 étape 0) et de la requête précèdent ceux de B2, puisque la fenêtre doit être connue avant S1.

**Limites de concurrence, dites sans détour.** Deux scans identiques, une tête de registre inchangée et des sources de `W` identiques **ne constituent pas un instantané transactionnel** : les trois familles (disque d'audit, registre, plan et split plan) sont lues à des instants différents ; le registre est append-only mais un ajout suivi d'un retour à la même tête est impossible, tandis qu'un enregistrement **ajouté après R2** n'est pas détecté ; un fichier de campagne modifié après S2 n'est pas détecté ; aucune chronologie, aucune preuve de temps. Ce sont des obligations d'E3-J (rescan indépendant, preuve de temps, lecture stricte au moment de l'admission). Aucun résultat positif de N2-b1 n'autorise une réservation ou une admission.

**Nouvelles dépendances et graphe d'imports (à amender dans les gardes de N2-a, décision D-b1-1).** Le protocole importera désormais : `gate_v_audit_registry` et `gate_v_audit_window` (nouveaux), `gate_v_exposure_inventory` (B4) et les types d'E3-A ; `gate_v_registry_store` est importé par `gate_v_audit_registry`, et `dataset_split` / `gate_v_campaign_plan_v2` **uniquement par `gate_v_audit_window`** (jamais par le protocole : le grep de sous-chaînes de N2-a interdit `load_data` et `ig_`, contenus dans `load_dataset_split_plan` et `config_`). Mesuré : importer `gate_v_registry_store` ou B4 ne charge ni B5, ni B6, ni `gate_v_registry_append`, ni `gate_v_registry_views`, ni les préconditions, ni `gate_v_campaign_manifest`. Il continue d'**interdire** : `gate_v_exposure_store` (B5), `gate_v_exposure_declarations` (B6), `gate_v_inventory_preconditions`, `gate_v_registry_append`, `gate_v_registry_views` (re-confirmation de slots), `gate_v_final_holdout_claim_acquisition`, `gate_v_campaign_manifest_v2`, `validate_gate_v_campaign_plan_v2_sources` (aucun appel). Note : `gate_v_registry_store` importe `atomic_json_store`, qui expose aussi des fonctions de publication ; le protocole n'en appelle aucune (test AST des appels).

## 8. API proposée

```python
@dataclass(frozen=True, kw_only=True)
class WindowSource:                      # NE REMPLACE PAS la fenêtre de l'opérateur : la confronte
    plan_root_label: str                 # racine CAMPAIGN_DIR propre (plan.json)
    split_plan_root_label: str           # racine SPLIT_PLAN_DIR (split_plan.json)

@dataclass(frozen=True, kw_only=True)
class RegistryConfig:
    root_path: str
    max_slots: int                       # sans défaut

# AuditRequest : champs de N2-a inchangés + deux champs optionnels (défaut None)
#   window_source: Optional[WindowSource] = None
#   registry: Optional[RegistryConfig] = None
```

Règles : **l'opérateur fournit toujours la fenêtre** (les trois champs de N2-a restent obligatoires et `window_declared_source` en entrée reste `OPERATOR_CONFIGURED`) ; `window_source` présent ⇒ la fenêtre dérivée doit lui être égale (`WINDOW_MISMATCH` sinon) ; absent ⇒ N2-a inchangé. Le **rapport** porte `window_declared_source = SPLIT_PLAN_REFERENCED` (nouvelle valeur de l'énumération) si et seulement si la dérivation a réussi, sinon `OPERATOR_CONFIGURED` ; `window_provenance` reste une **propriété dérivée** de ce champ (jamais un champ ni une entrée) : `OPERATOR_CONFIGURED` ↦ `UNVERIFIED`, `SPLIT_PLAN_REFERENCED` ↦ `SPLIT_PLAN_FINGERPRINT_MATCHED`. `registry` présent ⇒ B4 est assemblé (sinon `b4_completeness = NOT_BUILT` comme en N2-a). `registry` sans `window_source` est permis (fenêtre `UNVERIFIED` : le recoupement de 4.1.8 se fait alors contre la fenêtre de l'opérateur). Aucune vue, aucun contexte, aucun étage, aucun label dérivé, aucun chemin de lecteur interne n'entre par la requête (test de signature de N2-a étendu).

Rapport : champs ajoutés (4.2, section 6) ; `b4_inventory` passe de **propriété constante** à **champ** `b4_completeness` (amendement des tests d'invariants de N2-a, décision D-b1-1) ; les constantes d'autorité ne changent pas : `absence_evidence = UNAVAILABLE`, `grants = ()`, `persistence = NOT_PERSISTED`, `e3j_prerequisites_unmet` non vide, `not_proven`. Nouveaux codes de refus : `WINDOW_SOURCE_INVALID`, `PLAN_SPLIT_CONTRADICTION`, `WINDOW_MISMATCH`, `WINDOW_SOURCE_CHANGED`, `REGISTRY_UNREADABLE`, `REGISTRY_CHAIN_HEAD_CHANGED`, `STAGE_NOT_DERIVABLE`, `B4_ASSEMBLY_REFUSED` ; nouveau blocage : `DERIVED_COVERAGE_PARTIAL`. **Vocabulaire** : le contrôle de N2-a interdit les sous-chaînes `ADMISSION`, `CLAIM`, `ADMIT` dans les valeurs d'énumération et identifiants ; le rapport doit pourtant parler des types d'enregistrement du registre. Proposition (D-b1-7) : le rapport n'expose **aucun** nom d'étage ni de type d'enregistrement dans ses énumérations, champs ou identifiants publics ; `registry_record_counts` est un tuple de trois entiers dans l'ordre documenté (réservations, admissions, consommations), sans nom. Le contrôle de vocabulaire de N2-a ne porte que sur les noms (énumérations, `__all__`, champs) et non sur le contenu des tuples : **aucune exemption supplémentaire n'est nécessaire**.

## 9. Contrats de refus (synthèse)

| Code | Classe | Atteignable par l'API publique | Déclencheur |
|---|---|---|---|
| `WINDOW_SOURCE_INVALID` | R | oui | plan V2 / split plan illisible, absent, mal formé ; racine non configurée |
| `PLAN_SPLIT_CONTRADICTION` | R | oui | identifiant, empreinte, snapshot ou campagne contradictoires ; contre-contrôle de S1 en échec |
| `WINDOW_MISMATCH` | R | oui | fenêtre de l'opérateur ≠ dérivée ; fenêtre R / A / C propre ≠ `W` |
| `WINDOW_SOURCE_CHANGED` | R | oui (par faux injecté pour le test) | relecture finale différente |
| `REGISTRY_UNREADABLE` | R | oui | toute erreur du store ; mode `REAL` |
| `REGISTRY_CHAIN_HEAD_CHANGED` | R | oui (faux) | R1 ≠ R2 |
| `STAGE_NOT_DERIVABLE` | R | oui | table 5.4 |
| `B4_ASSEMBLY_REFUSED` | R | défensif | exception de B4 / E3-A |
| `RESOURCE_BUDGET_EXCEEDED` (existant) | R | oui | nombre de slots ou budget de lecture dépassé |
| `DERIVED_COVERAGE_PARTIAL` | B | oui | campagne de la chaîne sans racine configurée |

Les refus de N2-a restent inchangés. « Faux injecté » = remplacement par `mock.patch` du nom de la fonction de lecture dans le module qui l'appelle (`gate_v_audit_registry` ou `gate_v_audit_window`), sans paramètre privé (technique de N2-a).

## 10. Matrice de tests d'acceptation (RED → GREEN, à écrire avant le code)

Chaque cas : mise en place → attendu littéral. Les attendus sont écrits à part (jamais recalculés par le code testé).

| # | Cas | Attendu |
|---|---|---|
| 1 | W liée au split plan (plan V2 et split plan cohérents, `window_source` fourni) | `RECEIVABLE`, `window_provenance = SPLIT_PLAN_FINGERPRINT_MATCHED`, `W` = bornes normalisées de `final_holdout` |
| 2 | W configurée sans `window_source` | `UNVERIFIED`, comportement de N2-a identique octet pour octet (rapport égal) |
| 3 | `window_source` fourni ET fenêtre opérateur différente | `WINDOW_MISMATCH` |
| 4 | `split_plan_id` du plan ≠ celui du split plan | `PLAN_SPLIT_CONTRADICTION` |
| 5 | empreinte du plan ≠ `dataset_split_plan_fingerprint` recalculée | `PLAN_SPLIT_CONTRADICTION` |
| 6 | `dataset_snapshot_id` différent (plan vs split) | `PLAN_SPLIT_CONTRADICTION` |
| 7 | plan V2 absent / JSON invalide / version inconnue / champ manquant | `WINDOW_SOURCE_INVALID` (aucun repli sur l'opérateur) |
| 8 | split plan invalide sous `strict=True` | `WINDOW_SOURCE_INVALID` |
| 9 | plan modifié entre le chargement et S1 | `PLAN_SPLIT_CONTRADICTION` (contre-contrôle S1) |
| 10 | plan ou split plan modifié pendant l'audit (après le chargement initial) | `WINDOW_SOURCE_CHANGED` |
| 11 | registre absent / `identity.json` invalide / slot manquant / lien rompu / mode `REAL` | `REGISTRY_UNREADABLE` avec le code d'origine ; aucun statut de couche |
| 12 | registre sain vide | `RECEIVABLE`, `campaigns = 0` `OBSERVED`, étage `NO_OWN_RECORDS` interne ; autres compteurs `NOT_OBSERVED` |
| 13 | tête de chaîne modifiée entre R1 et R2 (faux qui ajoute un slot) | `REGISTRY_CHAIN_HEAD_CHANGED` |
| 14 | enregistrement propre dont la fenêtre ≠ `W` | `WINDOW_MISMATCH` |
| 15 | `RESERVATION` ou `ADMISSION` d'une autre campagne, fenêtre disjointe de `W` | non listée (règle de listabilité d'E3-A, qui ne vise que ces deux types) ; comptée dans `campaigns`. Une `CONSUMPTION` étrangère disjointe reste **listée** comme source exposante |
| 16 | enregistrement d'une autre campagne qui recoupe `W` | finding exposant listé ; `b4_completeness` inchangée. **Précondition** : la chaîne interdit le recouvrement de fenêtres entre campagnes ; le cas n'est atteignable que si la campagne propre est `ABSENT` du registre, ou pour une `CONSUMPTION` |
| 17 | attribution ambiguë : deux racines `CAMPAIGN_DIR` de même `expected_name` | `REQUEST_INVALID` (N2-a) ; aucune dérivation |
| 18 | racine de campagne dont l'ancre `plan.json` est incohérente | racine **statique**, jamais dérivée |
| 19 | campagne de la chaîne sans racine configurée | blocage `DERIVED_COVERAGE_PARTIAL` (label sentinelle) ; compte exact ; liste tronquée à 20 |
| 20 | Claim présent, registre `ABSENT` ou `RESERVED` | `STAGE_NOT_DERIVABLE` |
| 21 | `CONSUMED` sans Claim ; deux Claims | `STAGE_NOT_DERIVABLE` |
| 22 | `ADMITTED` + un Claim | étage `CLAIMED` interne ; aucune classification |
| 23 | comptabilité : toutes vues absentes | cinq compteurs `NOT_OBSERVED`, valeur 0 jamais `OBSERVED` ; `campaigns` seul `OBSERVED` |
| 24 | identifiants d'essais réutilisés / compteur partiel / non observé | non applicable à N2-b1 (aucune vue d'essais) : test que le protocole **n'en fournit aucune** (AST) |
| 25 | égalité **conditionnelle** `b4_completeness == b3_completeness` (API publique, sous les deux conditions de 6 (iii)) ; au niveau **adaptateur** seulement : vue construite sans racine statique | public : égalité sur tous les scénarios tant que les conditions tiennent (test de non-régression conditionnel, pas un invariant général) ; adaptateur : `INCOMPLETE` avec la raison `NO_STATIC_ROOT` quand B3 est `COMPLETE` |
| 26 | B3 incomplet | `b4_completeness = INCOMPLETE`, toutes les raisons de B3 conservées, aucune levée |
| 27 | invariant « B4 n'élargit pas B3 » | jamais `b4 COMPLETE` avec `b3 INCOMPLETE` (test paramétré sur les 33 scénarios de `SCENARIOS`) |
| 28 | ancien A0 v4 / v5 présent dans `exposure/` | lu seulement par S1 comme source de B3 ; **aucune requalification**, aucune lecture par le protocole |
| 29 | A0 relabellisé v6 (mêmes octets recalculés) | idem 28 ; le rapport ne cite aucune version d'A0 comme attestation |
| 30 | B6 sans contrôle de version | test de caractérisation : B6 non modifié, protocole n'importe pas B6 (D12) |
| 31 | aucune écriture | arbre du registre, de la campagne, des racines : empreinte identique avant / après, y compris sur refus |
| 32 | aucun droit RESERVATION / ADMISSION, aucun accès FINAL_HOLDOUT | `grants = ()`, aucun import de l'écriture de registre, du Claim, de B5, des préconditions |
| 33 | objets forgés : requête portant une vue, un contexte, une fenêtre sous forme d'objet | `REQUEST_INVALID` ; champs absents de la signature (AST) |
| 34 | concurrence : registre allongé pendant S2 ; plan remplacé pendant S2 | cas 13 et 10 |
| 35 | erreur de lecture : `OSError` pendant la lecture du plan, du split plan, du registre | refus typés correspondants, jamais d'exception |
| 36 | budget : `max_slots` dépassé ; budget total dépassé | `RESOURCE_BUDGET_EXCEEDED` **avant** toute lecture du registre (espion sur `read_registry`) |
| 37 | régression N2-a | les 155 tests collectés de N2-a (154 passés, 1 ignoré sous Windows) restent verts, à l'exception des tests amendés listés en D-b1-1 |
| 38 | vocabulaire fermé étendu | aucune valeur d'énumération ni identifiant public ne contient les sous-chaînes interdites ; exemption limitée au tuple de noms de types |
| 39 | graphe d'imports | modules interdits absents de `sys.modules` après import du protocole ; seuls les imports directs listés en 7 |

Mutations ciblées prévues (harnais jetable, une instance à la fois) : égalités de 4.1.5 une à une, relecture finale retirée, recoupement des fenêtres, table d'étage, règle de racine dérivée, copie de `complete`, constantes d'autorité.

## 11. Compatibilité historique

Aucun module existant n'est modifié : B2, B3 v4 / v5 / v6, B4, B5, B6, E3-A, L3-A, la garde de préconditions et le registre E3-D gardent identités, digests et comportement ; les A0 formats 1 et 2 restent lisibles ; `RulesVersions.is_current()` reste lié à v4. N2-a est **étendu**, non réécrit ; les seuls tests de N2-a à amender sont ceux qui figent explicitement le périmètre étroit, énumérés **exhaustivement** en D-b1-1 (neuf points). Les 154 autres comportements de N2-a restent verts sans modification. La garde D11 (B3 v6) n'est pas modifiée : le protocole reste son seul appelant. **Les A0 historiques ne sont jamais requalifiés** : le protocole ne lit aucun A0 ; un A0 présent dans une racine n'est vu que comme source de B3 (inchangé).

## 12. D12 et D13 : options et recommandations

**D12 — B6 doit-il imposer une politique de version avant d'utiliser un A0 ?**

| | Option 1 : B6 exige une liste blanche explicite de versions | Option 2 : B6 inchangé ; le futur processus d'admission ne fait jamais confiance à un A0 chargé, il relance l'audit et compare `inventory_id` |
|---|---|---|
| Sécurité | ferme la voie de lecture (aucun A0 de version non admise ne nourrit la lignée) | la voie de lecture B6 reste ouverte mais sans pouvoir : l'identité est recalculée par l'audit |
| Compatibilité historique | change la signature de `load_declaration_lineage` (paramètre obligatoire) : rupture de ses appelants et tests | aucune |
| Effet sur les identités | aucun (lecture seule), mais décide quels A0 « existent » pour la lignée | aucun |
| Complexité | modification d'un module publié et de ses tests | nulle maintenant ; discipline reportée à E3-J |
| Tests | tests de B6 par version, relabellisation v5 ↔ v6 | test de caractérisation de B6 non modifié |
| **Recommandation** | à décider quand `publish_audit_a0` sera conçu | **Option 2 pour N2-b1** : N2-b1 ne publie aucun A0 ; **condition suspensive** : aucun A0 produit par l'audit n'est écrit avant que D12 soit tranché (la relabellisation v5 ↔ v6 est indétectable : même `rules_digest`) |

**D13 — API publique de prévalidation B5 ?**

| | Option 1 : B5 expose une fonction publique de vérification de relecture | Option 2 : le protocole importe les fonctions privées `_prove_rereadable` / `_parse_record` |
|---|---|---|
| Sécurité | contrat explicite, testé par B5 | dépendance fragile à un nom privé ; un renommage casse silencieusement la prévalidation |
| Compatibilité historique | ajout pur, sans effet sur les formats ni les identités | aucune modification de B5, mais couplage caché ; viole l'esprit de la garde d'imports |
| Effet sur les identités | aucun | aucun |
| Complexité | petite modification additive de B5 | nulle en lignes, forte en risque |
| Tests | tests de la nouvelle fonction + caractérisation | tests de couplage fragiles |
| **Recommandation** | **Option 1, mais pas en N2-b1** : aucun A0 n'est construit en N2-b1 ; à traiter en N2-c (record pur) | rejetée |

B5 et B6 ne sont **pas** modifiés par cette note ; `publish_audit_a0` n'est pas conçu ici.

## 13. Décisions à approuver

| # | Décision | Recommandation |
|---|---|---|
| D-b1-1 | Étendre `audit_campaign_exposure` par deux blocs optionnels (`window_source`, `registry`, **défaut `None`**) plutôt qu'un second point d'entrée ; amender la liste **exacte** des tests de N2-a qui figent le périmètre étroit : (1) le jeu de champs d'`AuditRequest` (`test_gate_v_audit_protocol_request.py`) ; (2) `test_no_limit_has_a_default_value` : exempter les deux blocs, les plafonds restant sans défaut ; (3) le test de l'ensemble fermé des codes (`RefusalCode` à 18 valeurs, `BlockCode` à 2) ; (4) l'énumération `WindowProvenance` figée à `["UNVERIFIED"]` ; (5) `b4_inventory` constant et l'absence de `window_provenance` parmi les champs (`test_gate_v_audit_protocol_invariants.py`) — `window_provenance` reste une propriété ; (6) la liste blanche d'imports du protocole ; (7) l'absence de B4 dans `sys.modules` après import ; (8) le grep de sous-chaînes du source (`load_data`, `ig_`) : les imports de `dataset_split` et du chargeur de plan restent dans `gate_v_audit_window.py`, jamais dans le protocole ; (9) la garde D11 impose qu'aucun nouveau module ne contienne `gate_v_exposure_interpreters_v6` ni `gate_v_audit_protocol` (docstrings comprises) | oui |
| D-b1-2 | Niveau de provenance de `W` livré en N2-b1 : `SPLIT_PLAN_FINGERPRINT_MATCHED` seul ; `validate_…_sources` (sous-processus Git, six sources) reporté | oui ; niveau 2 en tranche ultérieure, avec décision sur l'effet de bord Git |
| D-b1-3 | Lecture du registre : `read_registry(barrier=True)` deux fois (avant S1, après S2), mode `SYNTHETIC` seul, refus de toute vue partielle | oui |
| D-b1-4 | Budget de lecture du registre : `RegistryConfig.max_slots` explicite et listage borné avant lecture (aucune modification du store) | oui |
| D-b1-5 | Comptabilité de N2-b1 : `AccountingViews()` vide ; seul `campaigns` observé ; cinq compteurs `NOT_OBSERVED` | oui ; les vues d'essais sont renvoyées à N2-b2 |
| D-b1-6 | Règle des racines dérivées (5.5) et blocage `DERIVED_COVERAGE_PARTIAL` | oui |
| D-b1-7 | Vocabulaire : aucun nom d'étage ni de type d'enregistrement dans les noms du rapport ; compteurs en tuple d'entiers à ordre documenté ; aucune exemption nouvelle | oui |
| D-b1-8 | Dérivation de l'étage propre avec le Claim de campagne (table 5.4) | oui |
| D-b1-9 | Exposer `inventory_id` (identité E3-A, diagnostic) dans le rapport ; ne pas exposer `inventory_content_digest` ni l'assemblage | oui, avec la mention « relancer l'audit » |
| D-b1-10 | B4 placé après S1 et avant S2 ; relectures finales (registre, plan, split plan) après S2 | oui |
| D12 | voir section 12 | Option 2 pour N2-b1, condition suspensive sur l'écriture d'A0 |
| D13 | voir section 12 | Option 1, en N2-c |

Questions ouvertes (non décidées par cette note) : valeurs opérationnelles des plafonds (D9 de N2-a) ; sort de N-VIDE-3 ; source future d'une `ClosingView` (qui produira un `ClosingRecord` ?) ; effet de bord Git acceptable pour le niveau 2.

## 14. Dépendances, risques et ce qui reste vrai

**Graphe de dépendances.**

| Élément | Existe | À créer | Décision |
|---|---|---|---|
| `read_registry`, `verify_chain`, `RegistrySnapshot` | oui | | |
| `load_gate_v_campaign_plan_v2`, `load_dataset_split_plan(strict=True)`, `dataset_split_plan_fingerprint`, `normalize_window` | oui | | |
| `assemble_exposure_inventory`, `OwnCampaignContext`, vues de B4 | oui | | |
| adaptateur de registre → vues | | `gate_v_audit_registry.py` | D-b1-3 à 6, 8 |
| dérivation de `W` | | `gate_v_audit_window.py` | D-b1-2 |
| extension de la requête et du rapport | | dans `gate_v_audit_protocol.py` | D-b1-1, 7, 9, 10 |
| vues d'essais, `ClosingRecord`, ingestion échouée, engagements nuls | **non** | N2-b2 ou plus tard | producteurs inexistants |
| `validate_…_sources` dans l'audit | fonction existe | intégration non conçue | D-b1-2 |
| record A0 pur, prévalidation B5 | partiel (privé) | N2-c | D12, D13 |

**Risques conservés, inchangés.**
- **T15** : coût mémoire de L3-A (`_cited_hashes`, pic d'environ 460 Mo pour un `validation_run.json` de 3,9 Mo, maximum et non somme) — non corrigé.
- **T16** : un `AuditReport` reste forgeable dans le même processus ; il n'a ni consommateur ni pouvoir.
- Validation Linux / POSIX non démontrée ; 64 tests ignorés sur Windows ; 13 erreurs historiques de l'arbre B isolé non rejouées.
- Aucune preuve d'antériorité du sceau ; aucune lecture réelle des workers ; L3-B (recalcul des faits S0) et E3-J (rescan indépendant, chronologie, attestation, autorisation, écrivain de registre) non réalisés.
- Nouveaux : **T17** coût de lecture du registre borné seulement par des constantes du store (5.2) ; **T18** deux lectures du registre et deux chargements du plan ne forment pas un instantané (section 7) ; **T19** la cohérence plan V2 ↔ split plan n'est pas une preuve de provenance (Décision 20.6) ; **T20** la comptabilité des essais est volontairement non observée : l'inventaire de N2-b1 ne peut pas servir de comptabilité de préadmission.
- La cohérence cryptographique (empreintes, chaîne) n'est jamais une preuve scientifique d'absence d'exposition : `absence_evidence` reste `UNAVAILABLE`.

## 15. Tranches d'implémentation minimales proposées

1. **N2-b1a — provenance de W** : `gate_v_audit_window.py`, bloc `window_source`, niveau `SPLIT_PLAN_FINGERPRINT_MATCHED`, garde de lecture préalable, refus 4.3, relecture finale, tests 1 à 10, 33 et la partie « plan et split plan » des tests 34 et 35, amendements D-b1-1. Aucune dépendance au registre ni à B4.
2. **N2-b1b — registre et B4** : `gate_v_audit_registry.py`, bloc `registry`, budget, étage, racines dérivées, assemblage B4, relecture de la tête, tests 11 à 32, 34 et 35 (partie registre), 36 à 39, dont les tests 28 à 30 (anciens A0, relabellisation, caractérisation de B6). Dépend de N2-b1a pour le recoupement de `W` (optionnel : il retombe sur la fenêtre de l'opérateur).
3. **N2-b2 (non conçue ici)** : vues d'essais et `ClosingView` — exige des décisions sur des producteurs inexistants.
4. **N2-c (non conçue ici)** : record A0 pur, D12 et D13.

Ordre recommandé : (1) acceptation de cette note ; (2) N2-b1a ; (3) N2-b1b ; la validation Linux se prépare en parallèle sans code.

## 16. Skills et outils utilisés

Invoqués : `development-orchestrator` (politique du dépôt), `domain-modeling` (vocabulaire seulement : **aucune** mise à jour de `CONTEXT.md`, qui porte des modifications étrangères), `codebase-design` (module, interface, couture, test de la suppression), `caveman` (hook de session). **Non invoqués** : `to-spec` (publie dans les GitHub Issues : sortant, contraire à « aucun commit, aucun push »), Spec Kit (dépôt non initialisé), `code-review` projet (aucun diff de code), Playwright, `/codex-orchestrator`, autopilote. Revue indépendante : voir l'addendum de la section 17.

## 17. Addendum — revue indépendante

Relecteur unique, agent `general-purpose`, contexte neuf, **lecture seule**, ≈ 9 min, 45 appels d'outils, vérification contre le code (HEAD `c97e394`). Verdict initial : « défaut bloquant de conception : OUI » — deux défauts HIGH à corriger avant toute implémentation ; l'architecture (deux modules internes, un point d'entrée, B4 entre S1 et S2) est jugée valide. **Onze défauts : 2 HIGH, 6 MEDIUM, 3 LOW ; tous corrigés dans cette note.** Les corrections n'ont **pas** été revues par un second relecteur (vérification interne seulement) : à faire avant l'implémentation de N2-b1a.

| # | Sévérité | Défaut | Correction |
|---|---|---|---|
| 1 | HIGH | `load_gate_v_campaign_plan_v2` et `load_dataset_split_plan` passent par `load_json_tolerant` : liens suivis, aucune taille maximale, clé dupliquée tolérée, FIFO bloquant ; lectures hors des protections et du budget de B2 | 4.1 étape 0 : `lstat` régulier non lien et taille ≤ `max_json_bytes` avant chaque chargeur, 4 lectures budgétées, autorité stricte = octets de S1 pour **les deux** fichiers (la racine du split plan est une racine configurée), relecture finale gardée ; exception explicite à la priorité des refus de B2 (section 7) |
| 2 | HIGH | liste des tests de N2-a à amender incomplète : test des valeurs par défaut, ensemble fermé des codes, énumération `WindowProvenance`, `window_provenance` non-champ, grep de sous-chaînes, garde D11 | D-b1-1 : neuf points exacts ; blocs optionnels à défaut `None` ; `window_provenance` propriété dérivée |
| 3 | MEDIUM | `load_dataset_split_plan(strict=True)` lève `ValueError` ; `normalize_window` refuse des formes que `build_split_boundary` accepte | 4.1 étape 4 : capture de `ValueError` et `TypeError`, refus `WINDOW_SOURCE_INVALID` |
| 4 | MEDIUM | test 25 inatteignable par l'API publique ; `b4_completeness` identique à `b3_completeness` en N2-b1 | section 6 et test 25 : invariant `b4 == b3` ; cas « B3 complet, B4 incomplet » au niveau adaptateur seulement |
| 5 | MEDIUM | tests 15 et 16 mal bornés (listabilité limitée à R et A ; recouvrement entre campagnes interdit par la chaîne) | tests 15 et 16 précisés |
| 6 | MEDIUM | `window_source` contradictoire (remplace / confronte) ; valeur `SPLIT_PLAN_REFERENCED` inexistante | l'opérateur fournit toujours la fenêtre ; la dérivée est confrontée ; la valeur est ajoutée à l'énumération du **rapport** ; niveau dérivé par propriété |
| 7 | MEDIUM | `DERIVED_COVERAGE_PARTIAL` incompatible avec `AuditBlock.root_label` ; liste jusqu'à 100 000 entrées | label sentinelle `(registry)` ; compte exact et 20 premiers identifiants |
| 8 | MEDIUM | comptage des slots = accès disque rangé en « mémoire » ; TOCTOU ; R2 sans comptage ; « 26 Gio » faux | 5.2 : comptage avant R1 et R2, limite TOCTOU dite, 24,4 Gio |
| 9 | LOW | `barrier=True` fait un `fsync` de répertoire (non « sans appel système d'écriture ») ; grep `load_data` / `ig_` ; garde D11 sur les sous-chaînes | 5.1, section 7, D-b1-1 (8) et (9) |
| 10 | LOW | motifs d'ancre B3 et forme du `source_id` du Claim non figés ; `campaign_id` du Claim peut valoir `None` | 5.4 et 5.5 : motifs exacts, attribution par `source_id`, tests de caractérisation |
| 11 | LOW | renvois (« voir 8 », « section 12 »), « 154 tests » (155 collectés), « 32 scénarios » (33), tests 28 à 30 sans tranche, tests 34 et 35 mal affectés | corrigés |

**Affirmations vérifiées exactes par le relecteur** : signatures de `read_registry`, `assemble_exposure_inventory`, `validate_gate_v_campaign_plan_v2_sources` ; le plan V2 porte `campaign_id`, `split_plan_id`, `split_plan_fingerprint`, `dataset_snapshot_id` et aucune fenêtre ; le chargeur du plan est pur (le Git est dans `gate_v_preregistration.py`) ; `dataset_split_plan_fingerprint` ne lit que des métadonnées ; l'empreinte de `PlanIndexEntry` coïncide avec celle de `dataset_split` pour un plan canonique ; le registre n'a ni `research_run_id`, ni stratégie, ni clôture, ni `snapshot_id` et aucune classe `ClosingRecord` n'existe ; table d'étage 5.4 cohérente avec `CampaignState` (une admission exige une réservation, une consommation exige une admission) ; chaîne vide : hash genesis hex64 valide ; `REBIND` sans `campaign_id` ; B4 : `AccountingViews()` donne `campaigns` observé et cinq compteurs non observés ; B6 charge tout A0 sans contrôle de version, `is_current()` sans appelant de production, `_prove_rereadable` et `_parse_record` privés ; importer `gate_v_registry_store` ou B4 ne charge ni B5, ni B6, ni l'écriture du registre, ni `gate_v_registry_views`, ni les préconditions, ni `gate_v_campaign_manifest` ; aucune lecture de FINAL_HOLDOUT, aucune écriture, aucun A0 introduits par la conception.

## 18. N2-b1a — révision de conception après la seconde revue indépendante, et implémentation locale (2026-11-03)

**Statut.** Implémentation LOCALE, non commitée, de la seule tranche N2-b1a (provenance de W). N2-b1b, N2-b2, N2-c, D12, D13, L3-B et E3-J restent PROPOSED et non implémentés. Cette section **remplace** les parties de 4.1, 4.3, 7, 8 et 9 qu'elle contredit ; le reste de la note n'est pas modifié.

### 18.1 Seconde revue (trois relecteurs indépendants, lecture seule) et arbitrage

Trois relecteurs (architecture et provenance ; adversarial ; tests et compatibilité) ont conclu « défaut bloquant de conception : OUI » pour la conception de 4.1, avec deux défauts de fond que la première revue n'avait pas vus :

1. **Les octets chargés n'étaient pas liés à ceux de S1.** Le garde `lstat` + taille laissait les chargeurs historiques (`load_json_tolerant`) rouvrir le chemin : clé dupliquée tolérée (la dernière gagne), `NaN` accepté, `RecursionError` non capturée, nom en casse différente lu sous NTFS alors que S1 ne voit pas le fichier, clé en trop sans effet sur l'empreinte recalculée mais refusée par S1. **Correction retenue : la dérivation se fait APRÈS S1 et ne s'appuie que sur les octets STRICTS de S1** (`content_bytes` et enregistrement analysé de l'observation). Le plan de split est reconstruit depuis cet enregistrement (sept clés exactes, textes non vides, bornes validées, forme canonique `asdict(plan) == enregistrement`) : aucun chargeur tolérant, aucune lecture disque, aucune horloge. Le plan de campagne V2 passe par son chargeur historique (structure et barrières internes), **encadré** par deux lectures gardées dont l'empreinte doit égaler celle de S1 ; ses quatre champs sont ensuite confrontés à l'enregistrement strict de S1.
2. **Écho de la source déclarée.** `window_declared_source` était recopié de la requête vers le rapport : dès qu'une valeur `SPLIT_PLAN_REFERENCED` existe, une requête pouvait l'affirmer sans dérivation. **Correction : seule `OPERATOR_CONFIGURED` est acceptée en entrée (`REQUEST_INVALID` sinon) ; la source du rapport est posée par le protocole après une dérivation ET une relecture finale réussies ; un rapport `REFUSED` ne peut pas porter `SPLIT_PLAN_REFERENCED`.**

Autres arbitrages : `WindowSource` ne porte que `split_plan_root_label` (la racine propre est unique, une seconde désignation serait une seconde source de vérité) ; les erreurs de configuration du bloc sont `REQUEST_INVALID` en mémoire (aucun accès disque avant le refus) ; une `Stage.WINDOW_SOURCE` est ajoutée ; la dérivation est confrontée à la fenêtre de l'opérateur (qui alimente S1) : `WINDOW_MISMATCH`, jamais de remplacement ; `window_provenance` reste une propriété dérivée de `window_declared_source` ; aucun champ n'est ajouté au rapport ; `_identity` n'est pas modifié (ses littéraux décrivent le scan ; les digests de N2-a restent identiques : mesure avant / après identique sur trois scénarios). N2-a ne pinnait aucun digest : trois digests F littéraux sont désormais épinglés par les tests.

### 18.2 Contrat livré

- `gate_v_audit_window.py` (interne, lecture seule) : `derive_window(...) -> DerivedWindow`, `recheck_sources(...)`, `WindowSourceRefused` (échec `INVALID`, `CONTRADICTION`, `CHANGED`). Imports : `dataset_split`, `gate_v_campaign_plan_v2` (déjà chargé par le protocole), `gate_v_exposure_interpreters`, `gate_v_exposure_scan`, `gate_v_exposure_sources`. Il ne nomme ni le protocole, ni les interpréteurs v5 / v6 (garde D11), n'écrit rien, n'ouvre aucune donnée de marché et n'appelle aucun sous-processus.
- Protocole : bloc optionnel `window_source: Optional[WindowSource] = None` ; quatre codes de refus (`WINDOW_SOURCE_INVALID`, `PLAN_SPLIT_CONTRADICTION`, `WINDOW_MISMATCH`, `WINDOW_SOURCE_CHANGED`) ; `WindowDeclaredSource.SPLIT_PLAN_REFERENCED` et `WindowProvenance.SPLIT_PLAN_FINGERPRINT_MATCHED`.
- Séquence : validation en mémoire, S1, recevabilité de N2-a, **dérivation de W depuis S1**, L3-A, S2, dérive F / I de N2-a, **relecture gardée finale des deux fichiers**, rapport.
- Budget : `+ 6 × max_json_bytes` si, et seulement si, `window_source` est configuré (split plan 1, plan 3, relecture finale 2).

### 18.3 Matrice des refus de la provenance de W

| Code | Étape | Déclencheur (testé sur disque) |
|---|---|---|
| `REQUEST_INVALID` | requête | `window_source` de type inexact ou sous-classe, label absent, label d'une racine qui n'est pas SPLIT_PLAN_DIR ; `window_declared_source` différent de `OPERATOR_CONFIGURED` |
| `RESOURCE_BUDGET_EXCEEDED` | requête | budget inférieur à lecture S1 + S2 + `6 × max_json_bytes` (borne exacte testée) |
| `WINDOW_SOURCE_INVALID` | après S1 | fichier absent ou non analysé par le scanner strict (JSON invalide, BOM, clé dupliquée, constante non finie, trop gros, dossier, nom en casse différente) ; split plan hors des sept clés, texte vide, borne invalide, non canonique ; plan refusé par son chargeur (y compris `RecursionError`) ; index des plans de l'interpréteur différent de la reconstruction ; fichier à plusieurs liens physiques ; lecture impossible |
| `PLAN_SPLIT_CONTRADICTION` | après S1 | `campaign_id`, `split_plan_id`, `dataset_snapshot_id` ou empreinte recalculée en désaccord (chacun testé seul) ; plan chargé différent de l'enregistrement strict de S1 |
| `WINDOW_MISMATCH` | après S1 | fenêtre de l'opérateur différente de la frontière `final_holdout` normalisée (jamais remplacée) |
| `WINDOW_SOURCE_CHANGED` | autour du chargeur et après S2 | octets du plan différents de ceux de S1 avant ou après le chargeur ; relecture finale différente (octets, nom en casse, point d'analyse) |
| refus de N2-a conservés | | `SCAN_STRUCTURAL_FAILURE` pour une racine vide (fichier manquant d'une racine par ailleurs vide), `RESCAN_FACT_DRIFT` pour un fichier modifié entre S1 et S2 |

### 18.4 Ce que `SPLIT_PLAN_FINGERPRINT_MATCHED` affirme et n'affirme pas

Affirme : les octets stricts observés par S1 pour `plan.json` (racine propre) et `split_plan.json` (racine configurée) se lisent comme un plan V2 et un plan de split valides, concordent sur la campagne, l'identifiant du plan de split, le snapshot et l'empreinte **recalculée** ; la fenêtre de l'opérateur est la frontière `final_holdout` de ce plan ; ces deux fichiers portaient encore les mêmes octets après le second scan. N'affirme **pas** : authenticité, conformité à la pré-enregistrement, à la `ResearchRun` ou à la politique (la revalidation par `validate_gate_v_campaign_plan_v2_sources`, avec Git, reste hors tranche), chronologie, instantané atomique, absence d'exposition, `FRESH`, ni aucun droit de réservation, d'admission ou d'accès au holdout. Un fichier modifié après la relecture finale, ou modifié puis restauré à l'identique, n'est pas détecté ; une falsification totalement auto-cohérente non plus (Décision 20.6).

### 18.5 D-b1-1 réduite à N2-b1a

Amendements de tests N2-a réellement nécessaires, **au nombre de six** (cinq confirmés par exécution avant toute correction, aucun autre échec ; le sixième a été forcé plus tard par la correction M2 de la revue de code, voir 18.6) : (1) jeu de champs de `AuditRequest` ; (2) `test_no_limit_has_a_default_value` (seule exemption : `window_source`) ; (3) ensemble fermé de `RefusalCode` (22 valeurs) ; (4) énumération `WindowProvenance` (2 valeurs) ; (5) liste blanche d'imports du protocole (+ `gate_v_audit_window`) ; (6) `report.not_proven` exact (+ `PLAN_SOURCES_AUTHENTICITY`, ajout additif visible aussi en mode N2-a). Autre durcissement de compatibilité : `AuditReport` refuse désormais une `window_declared_source` qui n'est pas exactement un `WindowDeclaredSource` (aucun consommateur de production). Ne cassent pas : `b4_inventory` constant, `window_provenance` non-champ, `sys.modules`, grep de sous-chaînes, garde D11 (contraintes respectées, pas amendements). Les quatre codes de registre, le point 5 (`b4_inventory`) et le point 7 (B4 dans `sys.modules`) de D-b1-1 relèvent de N2-b1b.

### 18.6 Validation de l'implémentation locale (mesures)

- **RED** : `tests/test_gate_v_audit_window.py` écrit avant le code ; première exécution en erreur de collecte (`ModuleNotFoundError: gate_v_audit_window`), ce qui prouve l'absence du module et non une régression ; les tests de caractérisation de N2-a (digests F littéraux, racine SPLIT_PLAN_DIR par le protocole) y sont inclus et ont été mesurés AVANT toute modification de `gate_v_audit_protocol.py`.
- **GREEN** : 87 tests N2-b1a collectés (86 passés, 1 ignoré : lien symbolique, `WinError 1314`). Suites N2-a : 5 échecs prévus et confirmés (champs de la requête, valeurs par défaut, ensemble fermé des codes, énumération de provenance, liste blanche d'imports) puis amendés minimalement ; le reste de N2-a est inchangé. Rapport de trois scénarios N2-a (digests F et I, raisons, blocs) identique octet pour octet avant / après.
- **Régression ciblée** (plan V2, split plan, sources, interpréteurs v4 / v5 / v6, différentiel, B5 v6, scanner, L3-A, magasin JSON, protocole) : 1994 passés, 13 ignorés (avant les tests ajoutés après la revue de code). **Suite générale unique sur le code final : 8125 passés, 65 ignorés, 0 échec, code 0, 18 min 39 s** (+66 passés, +1 ignoré par rapport à la publication de N2-a : 8039 passés, 64 ignorés).
- **Mutations ciblées** (harnais jetable, une instance à la fois, restauration des octets vérifiée par SHA) : 46 mutants. **40 tués** (appariements, index de B3 conjonct par conjonct, gardes de lecture, relectures finales, comparaison de fenêtre, source du rapport, budget, codes, invariants du rapport). **6 survivants, tous équivalents par redondance démontrée** : (m08) texte non vide et (m09) forme canonique se masquent mutuellement (la seule différence que `asdict` peut révéler est un `created_at` vide remplacé par l'horloge, déjà exclu par m08 ; `validate_portable_identifier` rend l'identifiant inchangé) ; (m16) test de fichier régulier doublé par l'échec d'`os.open` sous Windows et par `fstat` sous POSIX ; (m25) `value_parsed` implique `anomaly is None` par l'invariant du constructeur d'observation ; (m26) une clé (label, chemin) est unique par construction ; (m28) la taille est aussi bornée par la boucle de lecture. Aucune erreur de collecte n'a été comptée comme un mutant tué.
- **Revues indépendantes** : conception (3 relecteurs, 2 défauts HIGH de fond et 6 MEDIUM / LOW, tous intégrés avant le code) ; code final (1 relecteur, aucun défaut bloquant ; 2 MEDIUM et plusieurs LOW). Corrections après la revue du code : `AuditReport` refuse `SPLIT_PLAN_REFERENCED` sans fenêtre, sans empreintes S1 = S2 et sans racines de campagne et de plan de split (limite T16 : un rapport reste forgeable par `object.__new__`, il n'est pas un justificatif) ; `PLAN_SOURCES_AUTHENTICITY` ajouté à `not_proven` (lisible par machine : le plan V2 n'est pas revalidé contre ses sources) ; entrée d'index de B3 liée à la racine désignée par son `source_id` ; test renommé ; test à deux racines de plan de split. Chaque correction est couverte par un test et par un mutant tué. Le delta de ces corrections n'avait pas reçu de verdict exploitable lors de l'implémentation ; il a été revu ensuite (voir 18.8).

### 18.8 Revue indépendante finale du delta et gate de publication (2026-11-04)

Un relecteur indépendant (ECC `security-reviewer`, lecture seule, nouvelle instance, empreintes SHA-256 des six fichiers fournies et vérifiées) a relu en entier `gate_v_audit_window.py`, le diff du protocole et les amendements de tests, et a rejoué les trois fichiers de tests concernés (152 passés, 2 ignorés, dont le lien symbolique). Verdict : **`FINAL DELTA REVIEW PASS`**, aucun défaut HIGH ni MEDIUM. Quatre LOW, tous non bloquants : (1) cette note annonçait cinq amendements de tests N2-a au lieu de six (corrigé en 18.5) ; (2) le contrôle de type renforcé de `window_declared_source` dans `AuditReport` est un durcissement de compatibilité sans consommateur de production (consigné en 18.5) ; (3) le chargeur historique n'est entouré que de `OSError`, `ValueError`, `TypeError`, `RuntimeError` et `MemoryError` : une autre exception donnerait `AUDIT_INTERNAL_FAILURE` (refus typé et fermé) au lieu de `WINDOW_SOURCE_INVALID`, sans déclencheur concret trouvé ; (4) le garde construit en mémoire l'ensemble des noms d'une racine, sans plafond propre (risque de ressources local, borné en pratique par S1). Aucun correctif de code n'a été appliqué : les résultats de 18.6 (suite générale, mutations) restent valables parce que les six fichiers fonctionnels sont octet pour octet ceux qui ont été testés. Résidus inchangés : forgeabilité d'un `AuditReport` à champs cohérents (T16), absence d'instantané atomique, falsification entièrement auto-cohérente non détectable, aucune validation Linux / POSIX.

### 18.7 Limites exactes (inchangées ou nouvelles)

T15, T16, absence de validation Linux / POSIX (symlink, FIFO et reparse points réels non exercés : le test de lien symbolique est ignoré, le point d'analyse est simulé), T18 (aucun instantané atomique : deux scans et une relecture ne prouvent ni chronologie ni atomicité), T19 (cohérence plan V2 / plan de split, pas une provenance : `validate_gate_v_campaign_plan_v2_sources` et Git hors tranche), lecture non bornée du chargeur historique entre le garde et son appel (risque de mémoire seulement, l'empreinte rattrape ensuite), `st_ino` nul ignoré (l'empreinte rattrape). Aucun accès FINAL_HOLDOUT, aucun A0, aucun Claim, aucune écriture, aucune admission.
