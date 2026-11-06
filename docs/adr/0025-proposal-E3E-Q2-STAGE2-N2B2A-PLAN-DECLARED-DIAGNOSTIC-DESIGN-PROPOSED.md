# N-VIDE-2 / N2-b2a — diagnostic des déclarations des plans V2 (conception) — PROPOSED, révision 3

Statut : **conception PROPOSÉE (révision 3 approuvée par l'utilisateur le 2026-11-06) ; IMPLÉMENTÉE LOCALEMENT dans un worktree isolé, NON COMMITÉE (voir 16 : déviations D-impl-1 à D-impl-5, preuves, limites).** Les sections 5.2 (gestion des exceptions), 8 et 9 sont **remplacées** sur ce point par 16.1. Rédigé le 2026-11-06 sur `origin/master = e0bfae7ebacd7c03639c9ba94ce2115cd5551cf3` (N2-b1b publié). Révision 3 : intègre les trois revues indépendantes de la révision 1 et les trois confirmations de la révision 2 (architecture, sécurité, intégrité scientifique ; voir 14).
Cette note est **dédiée** (et non une section 20 de la note N2-b1) pour ne pas mélanger l'historique d'une note déjà longue de 19 sections avec une conception nouvelle. Les sections 5.6, 19.8 et T20 de la note N2-b1 restent vraies : les six compteurs de comptabilité de B4 ne changent pas. Les renvois « les vues d'essais relèvent de N2-b2 » (D-b1-5 ligne 311, lignes 334 et 350 de la note N2-b1) sont périmés par la décision de l'utilisateur ; une note de renvoi y est **prévue**, à poser dans le même commit que cette note de conception (10) ; elle n'est pas posée à ce stade.

`REAL` = DISABLED / NOT QUALIFIED · `GATE V` = NON PASSÉE · `FINAL_HOLDOUT` = NON ACCÉDÉ.

## 1. Décision de l'utilisateur, conséquence, et vocabulaire

L'utilisateur a retenu : A (exploiter les plans V2 pour des diagnostics **déclaratifs**), C (les compteurs scientifiques restent `NOT_OBSERVED` dans B4), B (producteurs réels reportés à des tranches séparées). L'injection d'identités simplement déclarées dans `AccountingViews.chain_trials` est **refusée**.

Conséquence : N2-b2a n'est **pas** de la comptabilité. C'est un **diagnostic descriptif séparé** de B4, exposé à côté des six compteurs et jamais à leur place. Il décrit ce que les plans de campagne V2 des autres campagnes de la chaîne du registre lue **promettent** ; il ne dit rien de ce qui a été exécuté.

Vocabulaire (pour éviter une collision avec Q-3). « **Déclaré par un plan V2** » désigne une valeur écrite par une machine dans `plan.json` et liée à `campaign_id` par une empreinte. Ce n'est **pas** un « nombre déclaré » au sens de Q-3 et de `declared_trial_counts` (ADR 0025 §23.11, §23.27.5 ; `CONTEXT.md`), qui sont des déclarations humaines de la chaîne de déclarations d'exposition, agrégées dans le `ClosingRecord` (Q-3). Pour la même raison, le nouveau champ, le type et le module n'emploient pas le mot « trial » (réservé à la comptabilité de B4) : ils disent « plan » et « research ».

## 2. Frontière scientifique (trois niveaux, jamais mélangés)

| Niveau | Contenu | Où il vit après N2-b2a |
|---|---|---|
| A. Déclaré par plan V2 | Références de run et configurations de recherche écrites dans les plans V2 | **Nouveau** champ `plan_declared_diagnostic` (ce document) |
| B. Exécution vérifiée | Essais réellement évalués, avec un artefact vérifié lié à la campagne | **Inexistant** : aucun producteur (voir 3 et 11) |
| C. Comptabilité scientifique | Six compteurs de B4 (`TrialAccounting`) | Inchangés : `campaigns` observé, les cinq autres `NOT_OBSERVED` |

Règles : (R1) un nombre du niveau A ne porte jamais le nom d'un compteur de C ; (R2) aucune valeur du niveau A n'entre dans `AccountingViews`, `CampaignTrials`, `TrialItem`, `inventory_id`, `inventory_content_digest` ni la classification ; (R3) aucune de ces valeurs n'est un N de multiple testing, ni une entrée d'un calcul de PBO ou de DSR (l'interdiction de 19.8 est étendue explicitement au diagnostic) ; (R4) `ClosingView`, vue V1, tentatives d'ingestion échouées et engagements nuls ne sont **jamais** construits, même vides.

## 3. Faits mesurés dans le code (HEAD e0bfae7)

**Producteurs existants.** Plan de campagne V2 (`save_gate_v_campaign_plan_v2`, `build_gate_v_campaign_plan_v2`) ; son chargeur `load_gate_v_campaign_plan_v2` qui recalcule l'empreinte de protocole puis le `campaign_id` ; observations strictes S1 de B2/B3 (le JSON de `plan.json` y est déjà parsé, `gate_v_audit_window.py:124-134`) ; `plan_root_attributed` (N2-b1b, `gate_v_audit_window.py:205-220`) qui rend un booléen ; registre E3-D (enregistrements R/A/C/REBIND, sans `research_run_id` ni stratégie).

**Producteurs inexistants (hors N2-b2a).** `ClosingRecord` (`final_holdout_closing_record.json`), enregistrements d'ingestion et de tentatives, enregistrement d'annulation d'engagement, énumérateur de campagnes V1 OOS, vérificateur d'artefact `ResearchRun` lié à une campagne, preuve des points de paramètres évalués. `research_run.json` n'est pas produit en pratique (`finalize_job` ne passe pas d'`experiment_id`). Aucune notion de « version de stratégie » : `BacktestManifest.strategy_version` reçoit le nom de la stratégie.

**Propriété exploitée, et sa portée exacte.** `campaign_id = H(version, preregistration_id, campaign_protocol_fingerprint)` ; l'empreinte couvre `research_run_id`, `research_run_content_hash`, `strategy_name`, `base_params`, `search_mode`, `search_space_hash`, `budget_per_fold` (`gate_v_preregistration.py:220-251`). Donc les champs lus sont **déterminés** par `campaign_id` (à collision de SHA-256 près) : un plan recopié sous le bon nom ne les change pas. Ils sont **déterminés, non authentifiés** : (a) rien ne lie `research_run_id` / `research_run_content_hash` à un `ResearchRun` réel (une référence de run est un texte libre) ; (b) `validate_gate_v_campaign_plan_v2_sources` n'est pas appelée (le chargeur dit que tout consommateur doit l'appeler avant de se fier à un plan ; ce diagnostic ne s'y fie pas, il décrit) ; (c) un auteur de plans peut produire autant de `campaign_id` valides qu'il veut, avec les mêmes références ; (d) une falsification totalement auto-cohérente n'est pas détectable (limite du chargeur, `gate_v_audit_window.py:6`). Ce lien prouve ce qui est **déclaré**, pas ce qui a été **évalué**.

## 4. Décisions définitives proposées

| # | Décision | Défaut |
|---|---|---|
| D1 | Exposition : un champ **séparé** `plan_declared_diagnostic` sur `RegistryAssessment` (obligatoire) et `AuditReport` (défaut `None`), `None` sans registre et pour tout rapport `REFUSED`. Refusées : fonction autonome non branchée (invisible dans le rapport), codage dans `trial_counters` ou `trial_counter_reasons` | oui |
| D2 | Entrée : uniquement les racines **déjà attribuées** par `plan_root_attributed` (liste `derived` existante). Aucune règle d'attribution nouvelle, **aucune lecture disque supplémentaire** : les faits viennent du JSON strict de S1 | oui |
| D3 | Identités : deux formules versionnées (5.3), SHA-256 sur JSON canonique, préfixes de domaine distincts de tout identifiant de B4. Pas d'empreinte d'ensemble dans le rapport (supprimée : aucun consommateur, risque de copie comme justificatif) | oui |
| D4 | Identité de configuration : `strategy_name` + `base_params` + `search_mode` + `search_space_hash`. **Sans** `budget_per_fold`, **sans** données ni split ni stratégie de code (donc « même configuration sur deux jeux de données » vaut une seule configuration : voir L3) | oui (alternative : ajouter le budget) |
| D5 | `_NOT_PROVEN` et `AUDIT_PROTOCOL_VERSION` du protocole **inchangés** ; le diagnostic porte sa propre propriété constante `not_established` | oui |
| D6 | Campagne propre exclue ; sa réutilisation d'un run ou d'une configuration d'une campagne antérieure n'est **pas** signalée (`OWN_CAMPAIGN_OVERLAP` dans `not_established`) ; extension P4 possible plus tard | oui (alternative : P4 dans cette tranche) |
| D7 | Échec par campagne = campagne `indisponible` avec code fermé ; jamais un refus de l'audit entier, jamais un compte falsifié | oui |
| D8 | Comptes `declared_*` : `0` seulement si le registre n'a aucune autre campagne ; `None` si des campagnes existent sans aucun fait ; entier ≥ 1 sinon. Comptes `multi_campaign_*` et conflits : `None` si moins de deux campagnes fournissent des faits (non calculable) | oui |
| D9 | Aucune modification de B3, B4, B5, E3-A, du registre, de L3-A, de N2-a, de `gate_v_audit_window`, ni du chargeur du plan V2 | oui |
| D10 | Garde de vocabulaire et D11 **écrits explicitement** pour le nouveau module (les gardes existantes ne couvrent ni ses énumérations ni ses champs) ; nom du module hors des préfixes interdits | oui |
| D11 | Contrôle d'identifiant : recalcul de `campaign_id` depuis les trois champs de l'enregistrement S1 — décrit comme contrôle de **cohérence interne**, pas comme défense ; pas de recalcul de l'empreinte de protocole (P1 non approuvée) ; la limite ABA L6 est documentée | oui (alternative : approuver P1) |

Restent **ouverts et non résolus ici** : Q-3, Q-5, D2 de B4, D12, D13, N2-c, L3-B, E3-J. Aucun n'est implémenté ni tranché implicitement.

## 5. Conception du module `gate_v_audit_plan_declared`

Module interne, **pur** (aucune écriture, aucune lecture disque, aucune horloge, aucun hasard, aucun sous-processus). Nom : `gate_v_audit_plan_declared.py` (aucun préfixe interdit par les gardes de `sys.modules` du protocole). Il ne doit contenir, même en docstring ou en commentaire : ni le nom du module du protocole, ni les noms des versions historiques de B3 (`gate_v_exposure_interpreters_v5`, `…_v6`, `interpret_audit_roots_v6`), ni l'expression `gate_v_k1s2_(verifier|observations|emptiness)`, ni les noms d'écriture interdits à l'adaptateur et à la fenêtre (`save_exclusive`, `save_atomic`, `load_json_tolerant`, `publish_*`, `subprocess`, `datetime`, accès d'attribut `.replace`, `.run`, `.time`…). Imports autorisés : `dataclasses`, `enum`, `hashlib`, `json`, `re`, `typing` ; `gate_v_campaign_plan_v2` (`GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION`, `compute_gate_v_campaign_id_v2` seulement) ; `gate_v_exposure_interpreters` (`RootLayout`) ; `gate_v_exposure_scan` (`EntryKind`). Ces trois modules « gate_v_ » sont déjà chargés par le protocole : le seul module nouveau est le sien.

### 5.1 Types

```python
PLAN_DECLARED_SEMANTICS_VERSION = "gate_v_plan_declared_v1"
MAX_CONFLICT_SAMPLE = 20
UNAVAILABLE_CODES = ("NO_ATTRIBUTED_ROOT", "PLAN_CAMPAIGN_ID_MISMATCH", "PLAN_FIELD_INVALID", "PLAN_RECORD_NOT_READ", "PREIMAGE_TOO_LARGE")   # ensemble FERMÉ, trié

class PlanDeclaredBasis(str, enum.Enum):
    REGISTRY_HAS_NO_OTHER_CAMPAIGN = "REGISTRY_HAS_NO_OTHER_CAMPAIGN"        # la chaîne lue n'a aucune autre campagne ; ne dit rien des campagnes V1, hors registre ou hors campagne
    EVERY_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ = "EVERY_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ"
    SOME_CHAIN_CAMPAIGNS_HAVE_PLAN_RECORD_READ = "SOME_CHAIN_CAMPAIGNS_HAVE_PLAN_RECORD_READ"
    NO_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ = "NO_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ"

@dataclasses.dataclass(frozen=True, kw_only=True)
class PlanDeclaredDiagnostic:
    basis: PlanDeclaredBasis
    source_campaign_count: int                     # autres campagnes de la chaîne dont les faits de plan ont été extraits
    unavailable_campaign_count: int                # autres campagnes de la chaîne sans faits
    unavailable_breakdown: tuple                   # ((code, n), ...) trié par code, n > 0, somme = unavailable_campaign_count
    declared_run_reference_count: Optional[int]    # couples (research_run_id, contenu) distincts
    declared_run_id_count: Optional[int]           # research_run_id distincts, comptés à part des couples (voir L8)
    declared_search_config_count: Optional[int]
    declared_strategy_name_count: Optional[int]
    multi_campaign_run_reference_count: Optional[int]    # références déclarées par au moins deux AUTRES campagnes de la chaîne, jamais avec la campagne propre : un réemploi, PAS un dédoublonnage d'essais ; un zéro ne signifie ni « aucun réemploi » ni indépendance de la campagne auditée
    multi_campaign_search_config_count: Optional[int]
    id_with_several_content_hashes_count: Optional[int]  # même research_run_id, contenus différents
    content_hash_with_several_ids_count: Optional[int]   # même contenu, identifiants différents (jamais honnête : le hash couvre l'identifiant)
    conflicting_run_id_sample: tuple               # identifiants triés, uniques, au plus MAX_CONFLICT_SAMPLE (peut être saturé par un auteur de campagnes ; les comptes restent exacts)

    @property
    def semantics_version(self) -> str: ...        # constante
    @property
    def scope(self) -> str: ...                    # constante "REGISTRY_CHAIN_PLAN_V2_ONLY"
    @property
    def not_established(self) -> tuple: ...        # constante, 5.6
```

Un registre sans autre campagne donne des comptes `declared_*` égaux à `0` : zéro constaté sur une chaîne vide, cohérent avec `campaigns = 0` observé par B4, et qualifié par `scope` et par la base ; ce n'est pas « aucune recherche déclarée » (campagnes V1, hors registre et hors campagne restent invisibles). Quelle que soit la base, **tous les comptes sont des minorants** de la recherche réelle (L1, L2) ; ce n'est pas une particularité de la base partielle. Le type n'a aucune propriété booléenne de verdict et aucun champ nommé `total`, `complete`, `overall`, `global` ni `all`.

### 5.2 Signature publique unique

```python
def diagnose(interpretation, *, derived: tuple, other_campaign_count: int, max_json_bytes: int) -> PlanDeclaredDiagnostic
```

- `interpretation` : l'interprétation B3 **de S1** (jamais S2).
- `derived` : tuple de couples `(label, campaign_id)` des racines déjà attribuées (sortie de `_derived_roots`, campagne propre déjà exclue). L'ordre d'entrée est indifférent (tri interne ; le résultat est le même).
- `other_campaign_count` : nombre de campagnes de la chaîne autres que la campagne propre.
- `max_json_bytes` : plafond explicite déjà exigé de l'opérateur (aucune valeur par défaut).
- **Préconditions, vérifiées dans cet ordre, avant tout index et toute boucle** : (1) `type(x) is int` (donc pas `bool`) pour `other_campaign_count` et `max_json_bytes`, avec `max_json_bytes ≥ 1` et `other_campaign_count ≥ 0` ; (2) `derived` est un tuple de couples `(str, str)`, étiquettes distinctes, identifiants distincts et de forme `gate_v_v2_<64 hexadécimaux minuscules>` ; (3) `other_campaign_count ≥ len(derived)`. Toute violation lève `ValueError` ou `TypeError` (erreur de programmation, jamais convertie en « campagne indisponible »). Le protocole garantit ces préconditions en amont (`gate_v_audit_protocol.py:515-517` : deux racines de même `expected_name` sont déjà refusées).
- **[Remplacé par 16.1, D-impl-1 : `MemoryError` et `RecursionError` se propagent]** **Après** les préconditions, `diagnose` n'échoue plus pour un contenu de plan : toute extraction par campagne (étapes 3 à 7, y compris `.encode("utf-8")` et les appels de bibliothèque) est enveloppée dans `except (ValueError, TypeError, KeyError, OverflowError, RecursionError, MemoryError)` ; `UnicodeEncodeError` est un `ValueError` ; `MemoryError` et `OverflowError` donnent `PREIMAGE_TOO_LARGE`, les autres `PLAN_FIELD_INVALID` (ou `PLAN_CAMPAIGN_ID_MISMATCH` pour l'étape 4). Aucune exception d'un plan hostile ne peut donc devenir `AUDIT_INTERNAL_FAILURE`.

### 5.3 Algorithme et formules d'identité (version 1)

1. **Index unique** : une seule passe sur les observations de S1 construit `{(root_label, relative_path): [observation]}` pour la disposition `CAMPAIGN_DIR` et le nom `plan.json`. Coût O(E). (La recherche par racine de `_observed` est en O(R·E) ; elle n'est ni modifiée ni réutilisée. Le module **reproduit** la sémantique de `_observed` — toutes les analyses de même disposition, nature fichier, sans anomalie, `value_parsed`, `content_hash` non nul, valeur de type `dict` — et un test de parité l'impose.)
2. Pour chaque `(label, expected)` : exactement une observation conforme, sinon `PLAN_RECORD_NOT_READ` (code défensif : inatteignable après `plan_root_attributed` hors remplacement de fonction en test ou ABA).
3. **Champs lus** (aucun autre) et **règles copiées du chargeur, sans plafond propre** (le chargeur n'en a pas ; `max_json_bytes` borne déjà tout) : `campaign_id` = `gate_v_v2_` + 64 hexadécimaux minuscules ; `campaign_plan_semantics_version` = `GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION` (**contrôlée en premier**) ; `preregistration_id`, `campaign_protocol_fingerprint`, `research_run_content_hash` = 64 hexadécimaux minuscules ; `research_run_id` = `[A-Za-z0-9_.-]+` sans `..` ; `search_space_hash` = **12** hexadécimaux minuscules (`gate_v_preregistration.py:75,128`, `gate_v_campaign_plan_v2.py:267`) ; `strategy_name` et `search_mode` = textes non vides après `strip` (aucune normalisation : `"A"`, `"a"` et `"a "` sont trois noms ; `search_mode` n'est pas confronté à l'ensemble fermé du chargeur, déjà imposé à l'attribution) ; `base_params` = objet JSON non vide. Typage strict (`bool` n'est pas un entier ; aucune coercition). Tout écart : `PLAN_FIELD_INVALID`.
4. **Contrôle de cohérence interne** : `compute_gate_v_campaign_id_v2(campaign_plan_semantics_version=…, preregistration_id=…, campaign_protocol_fingerprint=…)`, **appel par mots-clés obligatoire** (la fonction n'accepte que des arguments nommés), doit égaler `expected` **et** `record["campaign_id"]`, sinon `PLAN_CAMPAIGN_ID_MISMATCH`. Ce contrôle ne recalcule pas l'empreinte de protocole depuis les champs lus : il n'est donc **pas** une défense contre un enregistrement S1 qui différerait du plan validé par le chargeur (limite ABA L6) ; sa seule fonction est la cohérence des trois champs d'identifiant. Il n'est atteint par un cas réel qu'en cas d'ABA ou de remplacement de fonction.
5. **Canonicalisation** : JSON avec `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`, `allow_nan=False`, codé en UTF-8 (même algorithme que le plan V2). Plafond explicite de préimage : `8 × max_json_bytes` (la forme canonique peut grossir d'un facteur proche de 4 : `1e15` → `1000000000000000.0`), vérifié sur la taille encodée ; au-delà, `PREIMAGE_TOO_LARGE`.
6. **Référence de run déclaré** : préimage
   `{"declared_kind":"research_run_reference","identity_version":"declared_run_reference_v1","research_run_content_hash":H,"research_run_id":ID}`
   identité = `"declared_run_reference_v1_" + sha256(préimage).hexdigest()`.
7. **Configuration de recherche déclarée** : préimage
   `{"base_params":BP,"declared_kind":"search_configuration","identity_version":"declared_search_configuration_v1","search_mode":M,"search_space_hash":S,"strategy_name":N}`
   identité = `"declared_search_configuration_v1_" + sha256(préimage).hexdigest()`. L'ordre des clés de `base_params` est indifférent ; `10` et `10.0`, `true` et `1` ont des identités distinctes (comme dans l'empreinte de protocole).
8. **Agrégation** (déduplication par égalité exacte des chaînes) : nombre de campagnes par identité de référence et par identité de configuration ; `research_run_id → ensemble de hash` et `hash → ensemble d'identifiants`. Comptes : références distinctes ; `research_run_id` distincts ; configurations distinctes ; noms de stratégie distincts ; références et configurations déclarées par au moins deux campagnes ; identifiants à plusieurs contenus ; contenus à plusieurs identifiants. Échantillon = identifiants à plusieurs contenus, triés, au plus 20.
9. **Campagnes indisponibles** : `other_campaign_count − len(derived)` reçoivent `NO_ATTRIBUTED_ROOT` ; ce nombre égale `registry_uncovered_count` par construction. Le code mélange plusieurs causes (racine non fournie par l'opérateur, `plan.json` invalide ou falsifié, campagne V1 dans le registre) : les distinguer exigerait de modifier `_derived_roots` (D9) ; un dossier fourni mais invalide est pourtant plus grave qu'un dossier non fourni (L2). Chaque échec d'extraction ajoute un des quatre autres codes. Un échec d'extraction ne retire pas la campagne de `derived` : la couverture du registre ne bouge pas.

### 5.4 Vecteurs littéraux (à épingler dans les tests ; calculés avec les formules ci-dessus par un script indépendant du futur code, valeurs réalistes pour le chargeur : `search_mode` ∈ ensemble fermé, `search_space_hash` à 12 hexadécimaux)

| Entrée | Identité attendue |
|---|---|
| run : id `run_alpha`, contenu `"1"×64` | `declared_run_reference_v1_9176d54fb6c766a02f4159ea22e74336fbc7ef2b95b676bb623a3837d7b04a60` |
| même id, contenu `"2"×64` | `declared_run_reference_v1_9eb433dfe42646713184b66e93714eb0220b0379a11f9022988bcb6305652555` |
| config : `sma_cross`, `{"fast":10,"slow":30}`, `grid`, `0a1b2c3d4e5f` | `declared_search_configuration_v1_da64c7a0ff71a78cb74a433c32c2f63f5d375167b468b36bc7c431210e51938f` (identique avec `{"slow":30,"fast":10}`) |
| même config avec `"fast":10.0` | `declared_search_configuration_v1_efb577727387adc4a6568117e02982002de72177022be07c327b66e6f73b8ad0` |
| même config avec `"fast":true` | `declared_search_configuration_v1_76fa52cb0d4851bf03812cbead606c85bdc44ed6365b4a7ca74d0639c44e449d` |
| même config, `strategy_name` = `stratégie_é` | `declared_search_configuration_v1_164e07976a396fed8f574a08e48cf47920c69bd0e5e6842176c74f5b16bda44b` |

Préimage du premier vecteur de configuration : `{"base_params":{"fast":10,"slow":30},"declared_kind":"search_configuration","identity_version":"declared_search_configuration_v1","search_mode":"grid","search_space_hash":"0a1b2c3d4e5f","strategy_name":"sma_cross"}`. Garde contre la tautologie : ces littéraux sont la vérité ; le test recalcule en plus avec `json` et `hashlib` bruts, sans importer le module testé. L'agrégation est vérifiée par des **scénarios à k ≥ 2** (8), pas par un vecteur de digest.

### 5.5 Pas d'empreinte d'ensemble

La révision 1 proposait un `declared_set_digest`. Il est **supprimé** : aucun consommateur dans la tranche, non injectif vis-à-vis des champs exposés, et, comme `inventory_id` (D-b1b-2), une identité exposée peut être recopiée comme justificatif. Le déterminisme se teste par l'égalité des objets.

### 5.6 Propriété `not_established` (constante, exemption de vocabulaire du type de `E3J_PREREQUISITES_UNMET` : elle nomme ce qui manque)

`("EXECUTION_OF_DECLARED_RESEARCH", "EVALUATED_PARAMETER_POINTS", "V1_CAMPAIGNS", "CAMPAIGNS_OUTSIDE_REGISTRY", "RESEARCH_OUTSIDE_CAMPAIGNS", "RUN_ARTIFACT_VERIFICATION", "RUN_REFERENCE_AUTHENTICITY", "PLAN_SOURCES_CROSS_VALIDATION", "PLAN_ROOT_CONTENT_ATTRIBUTION", "STRATEGY_CODE_IDENTITY", "CONFIGURATION_DATA_BINDING", "OWN_CAMPAIGN_OVERLAP", "ABANDONED_FAILED_OR_VOID_ATTEMPTS", "MULTIPLE_TESTING_N")`.

## 6. Intégration et exposition

- **Adaptateur** (`gate_v_audit_registry`) : importe le module. `assess` appelle `diagnose(...)` **hors de tout `try/except`, après le calcul de la couverture** (le corps d'`assess` est déjà dans un `try/finally`, `gate_v_audit_registry.py:337-369`, qui ne convertit aucune exception et libère la poignée après l'appel) (après `gate_v_audit_registry.py:361`, donc après le contrôle `MAX_B4_REASONS` de `:353-354`), avec `derived=derived`, `other_campaign_count=len(chain_campaigns)`, `max_json_bytes=max_json_bytes`, et passe le résultat en argument nommé à la construction de `RegistryAssessment`. Raison : le test du durcissement qui remplace `_derived_roots` par `(("ghost", B),)` sur un registre vide (`tests/test_gate_v_audit_registry_hardening.py:223-229`) attend `RegistryAuditRefused("B4_ASSEMBLY_REFUSED", "ASSEMBLY")`, levé par l'assemblage **avant** ; un appel plus tôt ou dans le `try` de `:346-351` changerait ce comportement. L'appel de `assemble_exposure_inventory` reste **identique** (mêmes arguments, `AccountingViews()` vide). `RegistryAssessment` reçoit un dernier champ **obligatoire** `plan_declared_diagnostic` (sans défaut : un défaut `None` permettrait une évaluation sans diagnostic) ; la docstring « scalaires et tuples seulement » est corrigée (« scalaires, tuples et un diagnostic immuable »). `__all__` ajoute `PlanDeclaredBasis` et `PlanDeclaredDiagnostic` (ré-exports).
- **Changement de comportement de l'adaptateur appelé seul** : `assess` est dans `__all__` ; des `campaign_roots` avec des `expected_name` en double y étaient tolérés (dédupliqués par `covered`), ils lèvent désormais `ValueError`. Le protocole garantit l'unicité en amont.
- **Protocole** (`gate_v_audit_protocol`) : `from gate_v_audit_registry import … PlanDeclaredDiagnostic` (le protocole importe déjà ses types par l'adaptateur ; aucun nouvel import de module, aucun attribut d'adaptateur ajouté à la liste d'attributs lus). `AuditReport` reçoit un dernier champ `plan_declared_diagnostic: Optional[PlanDeclaredDiagnostic] = None` ; `registry_fields` le transmet. Aucun nouveau `BlockCode`, `RefusalCode` ni `Stage`.
- **S1 uniquement** : le diagnostic est calculé sur S1, avant S2. Une dérive de `plan.json` entre S1 et S2 est refusée par les empreintes de faits (`RESCAN_FACT_DRIFT`, `_fact_rows` inclut taille et hash des fichiers lus) ; une dérive du registre par R2. Dans les deux cas aucun rapport recevable n'existe, donc aucun diagnostic.
- **Conservation** : les six `TrialCounter`, `trial_counter_reasons`, `b4_*`, `registry_*`, `derived_root_labels`, la couverture, `inventory_id`, `inventory_content_digest` et la classification sont calculés **comme avant**, par les mêmes appels aux mêmes arguments ; le diagnostic est ajouté en aval, sans voie de retour.

## 7. Invariants

### 7.1 Du type `PlanDeclaredDiagnostic` (constructeur)

I1 types stricts (`int` non `bool`, tuples, énumération). I2 table de base : `REGISTRY_HAS_NO_OTHER_CAMPAIGN` ⇔ k = 0 et u = 0 (comptes `declared_*` = 0 ; comptes `multi_campaign_*`, conflits = `None` ; échantillon vide) ; `EVERY_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ` ⇔ k > 0 et u = 0 ; `SOME_CHAIN_CAMPAIGNS_HAVE_PLAN_RECORD_READ` ⇔ k > 0 et u > 0 ; `NO_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ` ⇔ k = 0 et u > 0 (tous les comptes `None`, échantillon vide). I3 si k > 0 : `declared_*` entiers avec 1 ≤ références ≤ k, 1 ≤ `declared_run_id_count` ≤ références, 1 ≤ configurations ≤ k, 1 ≤ noms ≤ configurations ; si k ≥ 2 les quatre comptes `multi_campaign_*` et conflits sont des entiers, si k = 1 ils valent `None` ; si entiers : 2 × `multi_campaign_run_reference_count` ≤ k, 2 × `multi_campaign_search_config_count` ≤ k, `id_with_several_content_hashes_count` ≤ `declared_run_id_count`, 2 × `id_with_several_content_hashes_count` ≤ références, 2 × `content_hash_with_several_ids_count` ≤ références ; `len(échantillon) = min(20, id_with_several_content_hashes_count)`. I4 `unavailable_breakdown` : codes de `UNAVAILABLE_CODES`, triés, uniques, comptes > 0, somme = u.

### 7.2 Des champs du rapport (extension des invariants 1 à 9 de 19.11 ; même message d'erreur « champs de registre »)

(10) `plan_declared_diagnostic is None` ⇔ `registry_id is None`, et, s'il n'est pas `None`, `type(plan_declared_diagnostic) is PlanDeclaredDiagnostic` (contrôlé avant toute lecture de ses champs, sur le modèle de `gate_v_audit_protocol.py:332-335`, pour que tout objet étranger lève la `ValueError` « champs de registre » et non une `AttributeError`), **testé avant le retour anticipé de la branche « registre absent »** (`gate_v_audit_protocol.py:343-346`) ; (11) `source_campaign_count + unavailable_campaign_count == registry_other_campaign_count` ; (12) `source_campaign_count ≤ len(derived_root_labels)` et `dict(unavailable_breakdown).get("NO_ATTRIBUTED_ROOT", 0) == registry_uncovered_count`. Le cas `REFUSED` est déjà exclu par l'invariant (7). Satisfiabilité vérifiée avec (9) : la somme des autres codes vaut `len(derived_root_labels) − source_campaign_count`. Limite inchangée : un rapport forgé par `object.__new__` reste possible (T16). La garde de vocabulaire (aucun champ ou propriété `complete`, `overall`, `global`, `all`, aucun membre contenant `inventory`) est une **garde statique de tests** (déjà en `tests/test_gate_v_audit_registry_protocol.py:330-335`), pas un invariant de constructeur.

### 7.3 Du module

M1 aucune lecture disque (AST : aucun `open`, `os`, `pathlib`, `subprocess`, `time`, `random`, `shutil`, `tempfile`). M2 résultat déterministe et indépendant de l'ordre d'entrée. M3 sorties bornées : échantillon ≤ 20, ventilation ≤ 5 couples. M4 mémoire O(k) identités plus O(taille d'un plan) transitoire ; temps O(E + Σ tailles des plans), un seul parcours de S1. M5 le module ne contient aucune des chaînes interdites listées en tête de 5.

## 8. Matrice de validation (RED d'abord ; fichier `tests/test_gate_v_audit_plan_declared.py` + un support de mondes)

| Groupe | Cas | Assertion GREEN |
|---|---|---|
| Identités | les six vecteurs de 5.4 ; ordre des clés ; `10`/`10.0`/`true` ; Unicode ; séparation de domaine run ≠ config | littéraux exacts ; recalcul brut indépendant |
| Réemploi | même run dans deux campagnes ; même config dans trois ; budgets différents, même config ; même config sur deux jeux de données | références 1, `multi_campaign_run_reference_count` 1 ; configuration 1 ; un seul compte malgré `budget_per_fold`, données ou split différents (L3) |
| Collisions | même `research_run_id`, deux contenus ; même contenu, deux identifiants (plan forgé) | deux références, un seul `declared_run_id_count`, `id_with_several_content_hashes_count` 1, échantillon contient l'identifiant ; second cas : `content_hash_with_several_ids_count` 1 |
| Bases et zéros | aucune autre campagne ; toutes couvertes ; partielle ; aucune couverte ; k = 1 | `REGISTRY_HAS_NO_OTHER_CAMPAIGN` comptes `declared_*` 0, `multi_*` `None` ; `EVERY_…` ; `SOME_…` comptes minorants ; `NO_…` comptes `None` (jamais 0) ; k = 1 : `multi_*` `None` |
| Plans manquants, mal formés, hostiles *(lignes « base_params très profond » et « MemoryError simulé » remplacées par 16.1)* | observation absente, multiple, anomalie, non analysée ; champ absent, mauvais type, `bool` pour un entier, hash en majuscules, `search_space_hash` de 64 caractères, identifiant avec `..`, version inconnue ; `campaign_id` ≠ attendu ; chaîne vide ; surrogate isolé (`UnicodeEncodeError`) ; `base_params` très profond ; préimage > `8 × max_json_bytes` (enregistrement S1 forgé directement, sans passer par le chargeur : un plan authentique ne l'atteint pas) ; `json.dumps` simulé levant `MemoryError` | une campagne indisponible avec le code attendu, **jamais** d'exception ni d'`AUDIT_INTERNAL_FAILURE`, les autres comptes intacts |
| Préconditions | `bool` pour un entier ; `derived` mal formé, doublons, identifiant mal formé ; `other_campaign_count < len(derived)` ; ordre d'entrée permuté | `ValueError`/`TypeError` avant tout index ; résultat identique pour deux ordres |
| Plans copiés | plan authentique sous le nom d'une autre campagne du registre ; plan d'une campagne hors registre ; plan authentique recopié dans le dossier correct | non dérivé ⇒ `NO_ATTRIBUTED_ROOT` ; hors registre non compté ; mêmes faits que l'original (déterminisme) |
| Parité chargeur | corpus de vrais plans (builder + sauvegarde + S1 réel), dont `search_space_hash` à 12 caractères et chaque `search_mode` | faits extraits = champs du plan chargé par `load_gate_v_campaign_plan_v2` ; aucune campagne authentique en `PLAN_FIELD_INVALID` ; parité du sélecteur d'observation avec `_observed` sur : observation multiple, anomalie, `value_parsed` faux, `content_hash` nul, valeur non `dict`, nature non fichier |
| Campagne propre | plan propre présent et attribué | exclu ; `OWN_CAMPAIGN_OVERLAP` dans `not_established` ; réutilisation non signalée (D6) |
| Registre | registre sans autre campagne ; R2 différent de R1 ; `_derived_roots` remplacé par `(("ghost", B),)` | `REGISTRY_HAS_NO_OTHER_CAMPAIGN` ; refus existant, aucun diagnostic ; refus existant `B4_ASSEMBLY_REFUSED` inchangé |
| Aucune lecture | espions sur `open`, `os.open`, `os.scandir`, `os.stat`, `os.lstat` autour de `diagnose` ; audit complet avec et sans le module | zéro appel dans `diagnose` ; appels de `_guarded_sha256` identiques à la référence (2 par racine candidate, plus 1 lecture du chargeur) |
| Bornes | 20 000 faits synthétiques ; ventilation ; plus de 20 conflits | un seul parcours de S1 (compteur d'accès) ; sorties ≤ bornes |
| Conservation B4 | mondes existants | `trial_counters`, `trial_counter_reasons`, `b4_*`, `registry_*`, couverture identiques aux valeurs d'avant ; `inventory_id`, `inventory_content_digest`, classification égaux à l'appel direct de `assemble_exposure_inventory` ; `AccountingViews()` vide transmis (test existant, non amendé) |
| Identités E3-A | formules E3-A | non touchées (aucun import ni appel nouveau) ; vecteurs historiques inchangés |
| Rapport | invariants (10) à (12) ; rapports forgés ; REFUSED sans diagnostic ; déterminisme sur deux audits | `ValueError` sur incohérence, même message « champs de registre » ; `None` ; objets égaux |
| Non-promotion | `grants == ()`, `absence_evidence` UNAVAILABLE, `not_proven` littéral inchangé, six compteurs : `research_runs`/`strategies` `None`/`NOT_OBSERVED`, `campaigns` observé ; `scope` et `not_established` littéraux | égalités exactes ; garde de vocabulaire écrite explicitement pour le nouveau module (noms publics, valeurs d'énumération, champs, codes, `__all__`, avec témoin de non-vacuité) |
| Graphe d'imports | import du protocole ; audit avec registre | `EXPECTED_GATE_MODULES` + 1 exactement ; aucun préfixe interdit ; chaînes interdites absentes du module |

Revue indépendante exigée avant approbation : sécurité, architecture, intégrité scientifique (14).

## 9. Budget

Lectures disque ajoutées : **0**. Le budget de lecture existant est inchangé : `plan_root_attributed` fait, **par racine candidate** (toute racine de campagne autre que la propre, pas seulement les racines dérivées), deux lectures gardées (`_guarded_sha256`) et une lecture du chargeur du plan V2. Une relecture de `plan.json` pour ce diagnostic est **refusée** : elle obligerait à amender cette formule. CPU : un parcours de S1 plus un SHA-256 par plan. Mémoire : O(k) identités de 100 octets environ ; l'observation JSON est déjà en mémoire (S1) ; transitoire d'au plus `8 × max_json_bytes` pour une préimage (plafond de 5.3 étape 5). En pratique le plafond n'est jamais atteint par un plan accepté par le chargeur (gonflement canonique d'environ 4,5 fois au plus, plan borné par `max_json_bytes` en S1) : `PREIMAGE_TOO_LARGE`, comme `PLAN_RECORD_NOT_READ` et `PLAN_CAMPAIGN_ID_MISMATCH`, est un code **défensif**, atteignable seulement par un enregistrement S1 synthétique, un ABA ou une erreur de mémoire simulée ; il ne constitue pas une protection.

## 10. Périmètre exact des fichiers et liste fermée d'amendements

**Nouveaux** : `gate_v_audit_plan_declared.py` ; `tests/test_gate_v_audit_plan_declared.py` ; un support de tests de mondes ; section d'`AI_HANDOFF.md` au moment de la publication seulement.
**Modifiés (code)** : `gate_v_audit_registry.py` (import, un champ obligatoire de `RegistryAssessment`, un appel dans `assess`, `__all__`, docstring) ; `gate_v_audit_protocol.py` (un import par l'adaptateur, un champ d'`AuditReport`, invariants (10) à (12), une ligne de `registry_fields`).
**Amendements de tests existants — liste fermée, QUATRE modifications** :
1. `tests/test_gate_v_audit_registry_protocol.py:376-380` : `EXPECTED_GATE_MODULES` + `gate_v_audit_plan_declared` (sert aussi aux tests `:397-415`).
2. `tests/test_gate_v_audit_registry.py:603-604` : liste blanche d'imports de l'adaptateur + `gate_v_audit_plan_declared`.
3. `tests/test_gate_v_audit_registry_closure.py:478-481` : le rapport valide à 2 campagnes non couvertes doit fournir un `plan_declared_diagnostic` cohérent (`NO_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ`, u = 2, ventilation `(("NO_ATTRIBUTED_ROOT", 2),)`, comptes `None`).
4. `tests/test_gate_v_audit_registry_protocol_hardening.py:86-89` : idem pour u = 21 (ventilation `(("NO_ATTRIBUTED_ROOT", 21),)`).
Ces deux derniers copient les champs d'un vrai rapport (qui contient un diagnostic `u = 1`) et changent les comptes ; sans amendement, l'invariant (11) les ferait échouer.
**Attendus verts sans amendement, à reconfirmer à l'implémentation** : `test_gate_v_audit_registry_hardening2.py:70-75`, `…protocol_hardening.py:67-83` et `:90-92`, `…closure.py:482-483` (attendent déjà une `ValueError` de la famille « champs de registre »), les gardes de vocabulaire par champs, le test `not_proven`, le test `AccountingViews()` du durcissement, `test_gate_v_audit_registry_hardening.py:223-229`, tous les pins de `trial_counters` et de `trial_counter_reasons`.
**Documentation seulement, à la publication** : note de renvoi sous D-b1-5 et aux lignes 334 et 350 de la note N2-b1 (« les vues d'essais ne seront pas alimentées par des identités déclarées : voir la note N2-b2a ») ; extension de l'interdiction PBO/DSR de 19.8.
**Non touchés** : B3 (v1 à v6), B4, B5, E3-A, registre (store, chaîne, modèle), L3-A, N2-a, `gate_v_audit_window`, chargeur du plan V2, tous résultats historiques.

## 11. Producteurs : existants et à créer

| Besoin | État |
|---|---|
| Plan V2 + chargeur + attribution + S1 | **existent** (utilisés tels quels) |
| Enregistrement `ClosingRecord`, tentatives d'ingestion, annulations d'engagement | **à créer** (tranches B séparées, après acceptation normative de l'ADR, Q-3 et D2) |
| Énumérateur de campagnes V1 OOS | **à créer** |
| Vérificateur d'artefact `ResearchRun` lié à une campagne ; preuve des points évalués | **à créer** |
| Version de stratégie / identité de code évalué | **inexistante** |

## 12. Risques et limites explicites

L1 **Déclaré ≠ exécuté** : une campagne réservée dont la recherche n'a jamais tourné est comptée ; une recherche qui a évalué des milliers de points n'ajoute qu'une configuration. Aucun de ces nombres n'est un N.
L2 **Minorants, quelle que soit la base** : un dossier retenu, absent, invalide ou non fourni retire une campagne (`NO_ATTRIBUTED_ROOT`, causes non distinguées) ; les campagnes V1, hors registre ou hors campagne (essais manuels) sont invisibles ; les chaînes lues sont synthétiques tant que le registre n'est pas lié au REAL.
L3 **Réemploi non interprété** : un run ou une configuration déclarés par plusieurs campagnes sont signalés, mais l'effet statistique du réemploi n'est pas interprété ; réutiliser peut augmenter l'exposition (liaison aux données non vérifiée) : ce n'est pas un doublon neutre. L'identité de configuration omet les données, le split, le budget, la géométrie walk-forward et le code de la stratégie (`CONFIGURATION_DATA_BINDING`, `STRATEGY_CODE_IDENTITY`).
L4 **Noms et flottants** : `strategy_name` non normalisé ; les flottants suivent la représentation de `json.dumps` de CPython 3 (comme l'empreinte de protocole) ; les vecteurs détecteraient un changement d'interpréteur. Un auteur peut aussi choisir un `search_space_hash` de 48 bits pour faire coïncider deux espaces ou réemployer des références fabriquées : le diagnostic décrit, il n'authentifie pas.
L5 **Copies** : un plan authentique recopié sous le bon nom fournit des faits identiques à l'original ; cela ne prouve pas que le dossier contienne les résultats réels (`PLAN_ROOT_CONTENT_ATTRIBUTION`).
L6 **Enregistrement S1 non lié à l'empreinte par un contrôle sur cet enregistrement (ABA)** : la revalidation de l'empreinte est faite par le chargeur, sur des octets liés à S1 par deux lectures gardées. Un adversaire **ayant un accès en écriture concurrent au dossier de campagne pendant l'audit** pourrait présenter un `plan.json` forgé à S1, aux deux lectures gardées et à S2 (mêmes octets), le plan authentique n'étant rétabli que pendant la lecture du chargeur : les faits forgés entreraient alors dans les comptes avec le bon `campaign_id`. Nouveauté par rapport à N2-b1b : l'ABA ne marquait qu'une racine « attribuée », il peut maintenant introduire du contenu forgé dans un diagnostic. La parade (P1, recalcul pur de l'empreinte depuis l'enregistrement) n'est pas approuvée ; la limite est consignée en toutes lettres.
L7 **Mauvais usage** : risque qu'un lecteur prenne `declared_run_reference_count` pour le nombre de runs évalués. Parades : noms, `scope`, `not_established`, absence de champ de verdict, absence d'empreinte copiable, garde de vocabulaire.
L8 **Unité différente de B4** : B4 dédoublonne par identifiant nu (`CampaignTrials.research_run_ids`) ; le diagnostic compte aussi les couples (identifiant, contenu). `declared_run_id_count` donne l'unité de B4 ; aucune adoption dans B4 n'est prévue ; toute proposition future serait d'un autre ordre.
L9 **Pas d'instantané atomique** : inchangé.
L10 **POSIX/Linux, noms 8.3, liens symboliques** : inchangés, non qualifiés.
L11 **Collision lexicale résiduelle** : `PARTIAL` existe déjà dans `CounterProvenance` et `RegistryCoverage` avec des sémantiques différentes ; la base du diagnostic utilise donc des valeurs distinctes (`SOME_CHAIN_CAMPAIGNS_HAVE_PLAN_RECORD_READ`).

## 13. Propositions distinctes (NON intégrées, chacune exige une approbation séparée)

P1 Fonction publique pure de reconstruction d'un plan V2 depuis un enregistrement (dans `gate_v_campaign_plan_v2`) pour recalculer l'empreinte de protocole sans disque dans le diagnostic ; réduirait L6. Modifie un module publié (ajout). La fonction publique `compute_campaign_protocol_fingerprint` existe, mais exige huit champs de plus et la reconstruction d'objets de spécification.
P2 Fonction publique d'accès à l'enregistrement strict d'un `plan.json` dans `gate_v_audit_window` (évite ~10 lignes dupliquées). Modifie un module publié.
P3 Chargeur de plan V2 borné (la lecture non bornée de `plan_root_attributed` est une limite connue de N2-b1b).
P4 Signalement du réemploi entre la campagne propre et les campagnes antérieures (la question la plus informative pour l'exposition ; les faits du plan propre sont déjà dans S1).
Aucune modification du contrat de B4 n'est nécessaire pour N2-b2a. Une vue « déclarée » dans B4 serait une proposition d'un autre ordre, refusée ici.

## 14. Revues indépendantes

**Révision 1 (trois relecteurs en lecture seule).**
- Architecture : accord avec changements. Bloquants : règle `search_space_hash` (64 au lieu de 12 hexadécimaux) et vecteur irréaliste ; liste fermée incomplète (deux tests existants copient un rapport réel). Majeurs : position de l'appel dans `assess` ; contrat d'exception incohérent (`compute_gate_v_campaign_id_v2` : arguments nommés, `ValueError`). Mineurs intégrés : validations copiées du chargeur, invariant (12) via `.get`, (13) déplacé en tests, champ obligatoire dans `RegistryAssessment`, budget par racine candidate, chaînes interdites, incohérences D8/I3, vocabulaire `ALL`, changement de comportement de `assess` appelé seul.
- Sécurité : sain avec changements. Bloquant : formats de 5.3 et vecteurs contredisant le chargeur (même point). Majeurs : ABA (documenté en L6, P1 non approuvée) ; « ne lève jamais » faux (capture élargie, `MemoryError` compris) ; « déterminé » ≠ « authentifié » (3, L4). Mineurs intégrés : plafonds divergents supprimés, plafond de préimage `8 × max_json_bytes`, ordre des préconditions, fuite par empreinte et échantillon, campagne propre.
- Intégrité scientifique : sain avec changements. Bloquant : vocabulaire d'exhaustivité (`ALL_OTHER…`, « exactement 0 ») → renommage, `scope`, minorants en toute base. Majeurs intégrés : collision avec Q-3 (vocabulaire, renommage « trial » → « plan »), réemploi non neutre (L3), `not_established` complétée (14 entrées), campagne propre (D6 documenté, P4 proposé). Mineurs intégrés : empreinte d'ensemble supprimée, comptes `multi_*` à `None` si k < 2, causes de `NO_ATTRIBUTED_ROOT`, contrôle d'identifiant reformulé, unité de B4, collisions lexicales, notes de renvoi dans N2-b1.

**Révision 2 : confirmation par les mêmes relecteurs.**
- Architecture : accord. Quatre mineurs rédactionnels intégrés (`try/finally` d'`assess`, doublon de lignes « attendus verts », plafond de préimage, type exact dans l'invariant (10)).
- Sécurité : sain. Les six vecteurs de 5.4 ont été recalculés par le relecteur avec un Python isolé et sont identiques. Mineurs intégrés : plafond de préimage défensif et test par enregistrement forgé, codes défensifs non présentés comme protection, parité de l'index avec `_observed` sur six cas, forme des identifiants de `derived` dans les tests existants (`foreign_id`, `"gate_v_v2_" + "cd"*32`) à reconfirmer à l'implémentation.
- Intégrité scientifique : sain avec changements (mineurs de rédaction, tous intégrés en révision 3) : définition de Q-3, `declared_run_id_count` sans mention de B4, docstring de `multi_campaign_*`, noms de base `…PLAN_RECORD_READ` (pas « FACTS »), justification des zéros, L3 et L8 reformulées, renvois N2-b1 « prévus ».

## 15. Statut

Conception PROPOSÉE, révision 3 ; implémentation locale décrite en 16 (non commitée). Revue indépendante satisfaisante : aucun constat bloquant ni majeur ne subsiste dans les trois confirmations ; les mineurs sont intégrés. Aucun code, aucun test nouveau, aucun commit, aucun push, aucune synchronisation du dépôt original.

## 16. Enregistrement d'implémentation (2026-11-06, LOCAL dans un worktree isolé, NON COMMITÉ)

Implémentation TDD de la conception de la révision 3 (décisions D1 à D11 approuvées par l'utilisateur ; P1 et P4 reportées, ABA documenté). Base : `origin/master = e0bfae7ebacd7c03639c9ba94ce2115cd5551cf3`. Le dépôt original (index préexistant, travaux étrangers) n'a été ni modifié ni synchronisé.

### 16.1 Déviations et précisions par rapport à la révision 3

| # | Déviation | Raison | Effet sur la note |
|---|---|---|---|
| D-impl-1 | `MemoryError` et `RecursionError` **ne sont pas capturées** dans `diagnose` : elles se propagent, le protocole les rend en `AUDIT_INTERNAL_FAILURE` ; seules `ValueError` et `TypeError` (données, dont `UnicodeEncodeError` et les clés mixtes sous `sort_keys`) donnent `PLAN_FIELD_INVALID`, `OverflowError` donne `PREIMAGE_TOO_LARGE` | mandat de l'utilisateur : une défaillance de mémoire ou de ressources ne doit jamais être dégradée en plan absent ou en rapport recevable | remplace 5.2 (dernier point), les lignes « base_params très profond » et « MemoryError simulé » de 8, et la mention « erreur de mémoire simulée » de 9 |
| D-impl-2 | contraintes I3 resserrées : `multi_runs <= refs`, `refs + multi_runs <= k`, `multi_configs <= configs`, `configs + multi_configs <= k`, `id_conflicts <= ids`, `ids + id_conflicts <= refs`, `(refs == ids) == (id_conflicts == 0)`, `2 × hash_conflicts <= refs`, `hash_conflicts == 0 ou ids >= 2` | les bornes de la révision 3 admettaient des objets impossibles ; chaque résultat de `diagnose` les satisfait (preuve par construction, relue indépendamment, et test de propriété sur 400 tirages) | remplace le texte de I3 (7.1) |
| D-impl-3 | `research_run_id` plafonné à 255 caractères (échantillon de conflits compris) | **divergence voulue avec le chargeur historique**, qui n'impose aucune longueur : borne la taille du rapport et correspond à la limite d'un nom de fichier ; un identifiant plus long rend la campagne indisponible (`PLAN_FIELD_INVALID`, minorant) | ajoute une règle à 5.3 (point 3) ; la parité « aucune campagne authentique en `PLAN_FIELD_INVALID` » vaut sous cette réserve |
| D-impl-4 | les comptes de déclarations **distinctes** (références, configurations, noms) sont **textuels** : `10` et `10.0`, deux graphies Unicode comptent pour deux ; ils ne sont ni des minorants ni des majorants stricts. Les comptes de campagnes et de déclarations lues restent des minorants | relecture de sécurité | précise 5.1, L1, L2, L4 |
| D-impl-5 | une `ValueError` de `compute_gate_v_campaign_id_v2` donne `PLAN_FIELD_INVALID` (et non `PLAN_CAMPAIGN_ID_MISMATCH`) | cas inatteignable : les trois champs sont déjà validés par les mêmes règles | précise 5.3 (point 4) |
| D-impl-6 | la première moitié de la clause (12) (`source <= len(derived_root_labels)`) est **impliquée** par (9), (11), la seconde moitié de (12) et I4 ; elle est conservée (spec 7.2) et aucun test ne prétend l'isoler | relecture d'architecture | précise 7.2 |
| D-impl-7 | un `assess` appelé seul avec deux racines de même nom attendu lève `ValueError` (déjà annoncé en 6) | précondition de `diagnose` | confirme 6 |

### 16.2 Fichiers (manifeste exact, aucun commit)

Nouveaux : `gate_v_audit_plan_declared.py` ; `tests/test_gate_v_audit_plan_declared.py` (171 tests) ; `tests/test_gate_v_audit_plan_declared_integration.py` (44 tests) ; `tests/gate_v_plan_declared_support.py` ; la présente note ; une section de `AI_HANDOFF.md` (§88).
Modifiés (code) : `gate_v_audit_registry.py` (import, ré-exports, champ obligatoire, un appel dans `assess`, docstrings) ; `gate_v_audit_protocol.py` (import par l'adaptateur, un champ, invariants (10) à (12), transmission).
Modifiés (documentation) : note N2-b1 (trois renvois et un paragraphe avant 19.9) ; `AI_HANDOFF.md`.
Amendements de tests existants — liste fermée de **quatre**, réalisés : `test_gate_v_audit_registry_protocol.py` (`EXPECTED_GATE_MODULES`), `test_gate_v_audit_registry.py` (liste blanche d'imports), `test_gate_v_audit_registry_closure.py` et `test_gate_v_audit_registry_protocol_hardening.py` (diagnostic cohérent dans le rapport copié). **Cinquième amendement P6** (approuvé par l'utilisateur le 2026-11-06, voir 16.5) : `test_rp1_clause_7_alone…` du même fichier de durcissement.
Non touchés (vérifié par différence à `e0bfae7`) : B3, B4, B5, E3-A, registre, L3-A, N2-a, `gate_v_audit_window.py`, chargeur du plan V2.

### 16.3 Preuves exécutées (lanceur D:, worktrees isolés)

- RED initial : `ModuleNotFoundError: gate_v_audit_plan_declared` à la collecte (tranche du module pur). Les tests d'intégration ont été écrits avant l'adaptateur et le protocole puis exécutés ensemble avec l'implémentation ; leur capacité à détecter l'absence de chaque morceau est établie par les mutants de 16.4, et non par un RED séparé.
- Tests ciblés (9 fichiers : les deux nouveaux et les sept fichiers de registre/protocole existants) : 504 passés, 1 ignoré (ignoré antérieur).
- Parité avec le chargeur : plans V2 réels (fabriques historiques) pour les quatre modes de recherche ; faits extraits égaux aux champs du plan chargé ; identités recalculées en JSON/SHA-256 brut sans importer le module.
- Aucune lecture disque ajoutée : espions sur `open`, `os.open`, `os.scandir`, `os.stat`, `os.lstat`, `os.listdir` autour de `diagnose` (zéro appel) ; comptage exact des lectures gardées (8) et du chargeur (4) pour quatre racines candidates ; gardes statiques (imports, noms interdits, aucune primitive d'E/S).
- Conservation de B4 : `assemble_exposure_inventory` reçoit `AccountingViews()` vide ; `inventory_id` et `inventory_content_digest` égaux aux formules E3-A appelées à part ; six compteurs épinglés (`campaigns` seul observé).
- Mutants ciblés (pilote `mutate_n2b2a.py`, lanceur D:) : tour 1, 57 mutants, 51 tués ; les 6 survivants (frontière du plafond, facteur 9, booléen comme compte, `id_conflicts <= ids`, clauses (11) et (12a)) ont conduit à renforcer les tests ; tour 2, 61 mutants, 59 tués ; survivants : une borne d'équivalence (tuée par un nouveau cas) et un mutant **équivalent** (contrôle de version déplacé après le format de l'identifiant : même code de sortie) ; tour 3 et 4 sur le code final : 6 mutants ciblés tués. La clause (12a) est un mutant équivalent (D-impl-6).
- Revues indépendantes en lecture seule (architecture, sécurité, qualité des tests), puis relectures de confirmation des correctifs : aucun constat HIGH ; tous les MEDIUM corrigés (spec écrite à jour, test dépendant de la plateforme supprimé, plafond d'identifiant documenté, tests renforcés).
- Suite complète : voir le paragraphe 88.3 de `AI_HANDOFF.md`.

### 16.4 Limites non qualifiées

L6 (ABA) inchangée ; P1 et P4 non approuvées ; ce diagnostic n'est ni une comptabilité, ni une preuve d'exécution, ni un N de test multiple ; aucun producteur réel n'existe (N2-b2b non conçu au-delà d'un brouillon) ; le registre lu est synthétique ; POSIX/Linux, noms 8.3 et liens symboliques non qualifiés ; plafond de 255 caractères sur `research_run_id` (D-impl-3) ; dépendance de B5/B6 inchangée (D12, D13 ouverts).
**Défaillances de ressources en amont (hors tranche, D9)** : `plan_root_attributed` (`gate_v_audit_window.py:218`) capture `RuntimeError` et `MemoryError` et rend « non attribué » ; `derive_window` (:186) convertit `MemoryError` en `WINDOW_SOURCE_INVALID` ; `_manifest_state` du protocole (`except Exception`) convertit une `MemoryError` en état illisible dans un rapport recevable. Ce n'est pas corrigé ici (D9 interdit de toucher ces modules) : **P5**, approuvée par l'utilisateur le 2026-11-06, resserre ces gestionnaires aux seules erreurs de données dans un **commit distinct** qui suit celui de N2-b2a (`fix(gate-v): preserve resource failure semantics in audit paths`) ; tant que ce commit n'est pas publié, les gestionnaires décrits ici restent en l'état.
**P6** (cinquième amendement, hors liste fermée) : réalisé, voir 16.5.

### 16.5 Clôture finale (2026-11-06) : P6

Constat : `test_rp1_clause_7_alone…` copiait le diagnostic de `good` (une campagne non couverte, `NO_ATTRIBUTED_ROOT` = 1) dans un rapport refusé dont `registry_uncovered_count` vaut 0 ; la clause (12) échouait donc aussi. Preuve avant correction : le mutant « clause (7) supprimée » survivait (test vert). Correction : le rapport refusé reçoit un diagnostic cohérent (une campagne attribuée dont le plan n'est pas lu, `PLAN_RECORD_NOT_READ` = 1) et un **témoin** vérifie que les mêmes champs, refus retiré, satisfont toutes les autres clauses de registre (objet forgé par `object.__new__`, appel direct de `_check_registry_fields`). Après correction : le mutant « clause (7) supprimée » est tué. Aucun code de production modifié par P6. Relecture indépendante en lecture seule du dernier delta (dont P6, le plafond de 255 caractères, I3 `id_conflicts <= ids` et le test de propriété à 400 tirages) : aucun constat HIGH ni MEDIUM ; le témoin a été revérifié clause par clause. Résultats de la suite complète : `AI_HANDOFF.md`, 88.3.

## 17. Tableau IMPLEMENTED / TESTED / REVIEWED / NON QUALIFIED

| Élément | IMPLEMENTED | TESTED | REVIEWED | NON QUALIFIED |
|---|---|---|---|---|
| Module pur `gate_v_audit_plan_declared` | oui (local) | oui | oui (3 relectures + confirmation) | ABA, authenticité des références |
| Intégration adaptateur et rapport (champ, invariants (10)-(12)) | oui (local) | oui | oui | — |
| Quatre amendements de tests et cinquième (P6) | oui | oui (P6 : mutant de la clause (7) tué) | oui | — |
| Identités et six vecteurs littéraux | oui | oui (recalcul brut indépendant) | oui (recalcul par la relecture de sécurité) | changement d'interpréteur |
| Conservation de B4, E3-A, classification | oui | oui | oui | — |
| Défaillances de ressources en amont | hors de ce commit (D9) | — | signalé | P5, commit distinct qui suit |
| Commit local, push | commit local (celui qui porte cette note) | — | — | push en attente d'approbation |
