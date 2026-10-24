# Plan TDD E3-E et matrice RED future — NON NORMATIF, NON ADOPTÉ

**Statut : PLAN PROPOSÉ (2026-10-20), révision 6 (corrigé après six revues indépendantes : `…-REVIEWS.md`). Aucun test de ce document n'existe ; aucune tranche ne démarre avant l'acceptation des décisions `N*` de `0025-proposal-E3E-DECISIONS-PENDING.md`.**
Compagnons : `…-CONTRACT-SPEC-PROPOSED.md` (contrats), `…-23.32-ATTESTATION-F1-F5-PROPOSED.md` (F1/F5), `…-HASH-VECTORS.json` (vecteurs).
Toutes les fixtures sont **synthétiques**. Aucun test ne lit le `FINAL_HOLDOUT` ni des données de marché (garde AST + garde de chemin, R-46). `REAL` = DISABLED / NOT QUALIFIED. `GATE V` = NON PASSÉE.

## 1. Règles d'exécution de chaque tranche

1. `git status --short` et empreinte de l'index (`git diff --cached | sha256sum` = `8b78a333…6e6f`) avant et après ; travaux étrangers préservés ; aucun commit sans autorisation explicite.
2. Ordre : **RED** (les tests échouent pour la bonne raison, montrés) → **GREEN** minimal → refactor → revue indépendante en lecture seule → suite de régression → mutation ciblée sur copie hors dépôt (baseline verte exigée d'abord).
3. Régression minimale avant GREEN et après : `tests/test_gate_v_final_holdout_protocol*.py` (E3-A), `tests/test_gate_v_exposure_*.py` (B3–B6), `tests/test_atomic_link_publication*.py` (E3-C), `tests/test_gate_v_registry_*.py` (E3-D, 429 + 10 ignorés sous Windows ; 439 sous Linux) et les tests de claim E2.
4. Un module = un fichier ; aucun module publié n'est modifié sauf **S-0b** (C-16, une ligne de B4 + un test amendé) et **S-5a** (B3 v4 minimal, tests publiés amendés), chacun avec décision préalable ; **E3-C n'est pas modifié** (N9 réutilise `TempNaming.EXPOSURE`).
5. Vérification Linux via GitHub Actions sur branche temporaire (méthode d'E3-C/E3-D) pour les tranches qui touchent le système de fichiers ; nettoyage des branches temporaires hors périmètre sans autorisation.
6. Les tailles ci-dessous sont des **estimations de travail**, non des mesures.

## 2. Tranches

| ID | Contenu | Fichiers prévus (noms PROPOSÉS) | RED (IDs de la matrice) | Bloquée par | Estimation |
|---|---|---|---|---|---|
| **S-0** | Décisions utilisateur N1…N20 et C-16 (matrice finale) | — | — | humain | — |
| **S-0b** | **E3-E0c** correction du défaut latent `RegistryRecordFact.seq >= 1` (registre numéroté depuis 0, C-16) | modification de `gate_v_exposure_inventory.py` + test | R-55 | décision utilisateur (module B4 publié) | ~6 tests |
| **S-1** | Canonicalisation commune et test des vecteurs **indépendant** : recalcule V1–V10 depuis des littéraux (sans import de production), compare au module | `tests/test_gate_v_e3e_vectors.py` (+ lecture du JSON) | R-01…R-04 | N1 (V1–V4) ; N3/N5 (V5, V9) ; N10 (V6) ; N18 (V10) | ~12 tests |
| **S-2** | **E3-E1** attestation : modèle pur (32 clés), hash F5, sérialisation, relecture stricte | `gate_v_attestation.py`, `tests/test_gate_v_attestation.py` | R-01…R-04, R-06…R-11, R-48, R-50, R-56, R-65 | N1, N2, N16 | ~70 tests |
| **S-3a** | **E3-E2a** vérification d'attestation, volet **interne** (relecture, A0, déclarations, lignée, préfixe, classification, éligibilité, mode, `time_proof_type`) | `gate_v_attestation_verify.py`, `tests/test_gate_v_attestation_verify.py` | R-12, R-13, R-47, R-48, R-51, R-63, R-66 | S-2 | ~50 tests |
| **S-3b** | **E3-E2b** volet **liaisons** (engagement, attachment, preuve de temps, faits de chronologie 23.32.4 bis) | idem | R-12 (STALE_COMMITMENT/ATTACHMENT/TIME_PROOF), R-53 | S-3a, S-8, S-9, S-10 | ~25 tests |
| **S-4** | **E3-E4** autorisation : modèle, hash, relecture, liens à l'attestation, au Claim, au mode | `gate_v_authorization.py`, `tests/test_gate_v_authorization.py` | R-32…R-34, R-52, R-65 | N10 | ~45 tests |
| **S-5a** | **E3-E0a** B3 v4 **minimal** (prérequis dur) : règles informatives pour les noms E3-E et l'orphelin `.exposure.tmp.*` à la racine de campagne, `rules_digest` v4 mesuré et figé, `KNOWN_B3_VERSIONS`, lecture historique v2/v3 ; **aucun champ ajouté** ; amende `tests/test_gate_v_exposure_integration.py` et `tests/test_gate_v_exposure_store.py` | modifications de `gate_v_exposure_interpreters.py` + `tests/test_gate_v_exposure_interpreters_v4.py` | R-41, R-58, R-77 | N8 | ~35 tests |
| **S-5b** | (optionnel, N19b) champ additif `view_marker` de `SourceInterpretation` + garde B5 | `gate_v_exposure_interpreters.py`, `gate_v_exposure_store.py` | R-24 (variante marqueur) | N19b | ~10 tests |
| **S-7** | **E3-E3** F1 : `build_attestation_observation`, `history_digest`, `verify_observation_against_disk`, **étape 11 bis (recontrôle pré-Claim)**, tableau des slots postérieurs, `recompute_post_admission_view` (scalaires seulement, relit le registre) | `gate_v_attestation_observation.py`, `gate_v_postadmission_view.py`, tests | R-05, R-14a/b, R-15…R-24, R-49, R-59, R-60, R-64, R-68…R-72 | **N4–N7, N19** (SPEC BLOCKED) | ~100 tests |
| **S-8** | **E3-E5** engagement : modèle, ids (hash sémantique + hash de contenu), relecture, liaison plan / pré-enregistration / code courant | `gate_v_commitment.py`, tests | R-37, R-65 | N18 | ~70 tests |
| **S-9** | **E3-E6** preuve de temps : modèle, machine d'états, `TimeProofFact`, `SYNTHETIC_FIXTURE` ; **aucun** vérificateur RFC 3161/OTS réel | `gate_v_time_proof.py`, tests | R-25…R-31, R-62, R-65 | N11–N13 | ~60 tests |
| **S-10** | **E3-E7** attachment (depuis `IngestionRecordRef`) et `CommitmentVoidRecord` | `gate_v_attachment.py`, `gate_v_commitment_void.py`, tests | R-35, R-36, R-38, R-54, R-65 | N14, N17 | ~55 tests |
| **S-11** | **E3-E8** témoin de tête : modèle + détection | `gate_v_head_witness.py`, tests | R-39, R-61 | 23.24 (support) pour l'émission seulement | ~35 tests |
| **S-12** | **E3-E9** rapport de prérequis d'`ADMISSION` en lecture seule (**descriptif, sans booléen « ok »**) | `gate_v_admission_prerequisites.py`, tests | R-32…R-34, R-43…R-46, R-67 | S-3a, S-3b, S-4, S-7…S-11 | ~50 tests |
| **S-13** | Revue adversariale finale, mutation, validation Linux, errata, handoff | — | toutes | tout | — |

**Hors E3-E (E3-J ou E3-D v2)** : API de publication vérifiante de `RESERVATION` et `ADMISSION`, sept contrôles de 23.27.4 répétés après conflit, étape 8, dérivation de l'étage, `EXECUTION_VOID_<cause>`, `ClosingRecord`. **Hors E3-E (E3-F)** : `IngestionRecord`, ingesteur, coffre scellé. **Hors E3-E (E3-Q)** : rapport de qualification `REAL`.

Chemins critiques : S-0b → S-2 → S-3a → S-4 → **S-5a** (B3 v4 : condition **nécessaire** de toute admission de bout en bout, que le handoff § 64.6 avait omise, mais **non suffisante** : un dossier V2 réel reste `UNDETERMINED` tant que Q-2 et l'interprétation de `manifest.json`, `validations/`, `technical_failure.json`, `manifest.update.lock` ne sont pas tranchées — C-29) → S-3b → S-12. S-7 reste la seule tranche dont la spécification est bloquée.

## 3. Matrice RED future (fixtures synthétiques uniquement)

Colonnes : **Cas** · **Attendu** · **Tranche**. Les cas qui **caractérisent une limite** (et non une garantie) sont marqués ◇ : le test documente le comportement, il ne le promet pas.

### A. Hash et schéma de l'attestation
| ID | Cas | Attendu | Tranche |
|---|---|---|---|
| R-01 | Record V1 : hash recalculé par le module = vecteur indépendant | égal ; la préimage fait 2 010 octets (32 clés) | S-1, S-2 |
| R-02 | V2 : attestant non ASCII en NFC | hash = vecteur ; `ensure_ascii=True` et NFD donnent d'autres hashs (contre-vecteurs refusés comme formes) | S-1, S-2 |
| R-03 | Hash incorrect : un octet de `attestation_content_hash` modifié | `ATTESTATION_INVALID` | S-2 |
| R-04 | Ordre d'insertion des clés ; valeur placeholder de la clé exclue ; `attestation_seq` 1 vs 2 | hash identique pour l'ordre et le placeholder ; hashs distincts pour la seq | S-1, S-2 |
| R-05 | Hash stocké ≠ hash recalculé, record bien formé, **pinné par l'`ADMISSION`** (nécessite le contexte de l'`ADMISSION` : pas un test de modèle pur) | `ADMITTED_ATTESTATION_REPLACED` | S-7 |
| R-06 | Champ manquant (chacune des 32 clés, une à la fois) | `ATTESTATION_INVALID` | S-2 |
| R-07 | Champ inconnu / supplémentaire | `ATTESTATION_INVALID` | S-2 |
| R-08 | Flottant, `null`, texte NFD, substitut isolé, caractère de contrôle, instant non normalisé | `ATTESTATION_INVALID` | S-2 |
| R-09 | `version` inconnue ; version connue antérieure | `ATTESTATION_VERSION_UNKNOWN` ; lecture historique intègre marquée non courante | S-2 |
| R-10 | `attestation_seq` ≠ nom du slot ; `inventory_id` ≠ répertoire ; `campaign_id` ≠ attendu | `ATTESTATION_INVALID` / `ATTESTATION_CAMPAIGN_MISMATCH` | S-2 |
| R-11 | JSON valide mais octets ≠ sérialisation normative (indentation, ordre, CRLF, BOM) | refus (point fixe) | S-2 |
| R-12 | Champ altéré **avec** hash recalculé (ex. `inventory_content_hash`, `static_sources_digest`, tête de déclaration, préfixe de registre) | hash valide, attestation **périmée** : `ATTESTATION_STALE_*` ; jamais `ATTESTATION_INVALID` | S-3a (périmé interne), S-3b (liaisons) |
| R-13 | Attestation citant le hash d'un A0 illisible | `A0_PIN_UNRESOLVED` (B6, inchangé) | S-3a |

### B. Slots, chronologie des attestations et F1
| ID | Cas | Attendu | Tranche |
|---|---|---|---|
| R-14a | **Reprise après crash AVANT le Claim** : slot `seq > pinned` apparu entre l'`ADMISSION` durable et le Claim | la reprise **continue** l'ADMISSION autoritative (aucun candidat reconstruit), l'étape 11 bis réussit sur les artefacts **épinglés**, le slot postérieur est sans effet et consigné ; un candidat reconstruit « à la hauteur courante » échouerait en `CAMPAIGN_ALREADY_REGISTERED` (test de contraste) | S-7 |
| R-14b | **Reprise avec un Claim local déjà acquis** (même slot postérieur) | la reprise est **refusée** (`AlreadyInProgressOrConsumed` / `CLAIM_ONLY` à régulariser) comme R-79 ; le tableau 23.32.6.5 des slots postérieurs ne s'applique qu'à l'étape 13 (post-Claim) ; aucun `CAMPAIGN_ALREADY_REGISTERED` | S-7 |
| R-15 | **Slot épinglé absent** après l'`ADMISSION` | `ADMITTED_ATTESTATION_MISSING` | S-7 |
| R-16 | **Slot épinglé non terminal** au moment de l'`ADMISSION` (`highest > pinned`) ; le code `highest_attestation_slot` de B6 existe déjà : la partie caractérisation est en S-3a | aucune observation valide, `ADMISSION` non publiable (attestation périmée) | S-3a, S-7 |
| R-17 | **Slot ajouté concurremment** entre les deux lectures de la double lecture | `ATTESTATION_UNSTABLE`, rien de publié | S-7 |
| R-18 ◇ | Slot ajouté entre la dernière lecture et le `link` (fenêtre résiduelle) | l'`ADMISSION` est publiée, le slot est classé « postérieur à l'observation » et consigné ; le test **documente** la limite, ne la promet pas | S-7 |
| R-19 | **Attestation historique modifiée** (slot `< pinned`) en JSON valide | `ADMITTED_ATTESTATION_HISTORY_ALTERED` ; B3 reste `complete = True` (preuve que `history_digest` détecte ce que B3 ne détecte pas) | S-7 |
| R-20 | Slot historique rendu illisible | `ADMITTED_ATTESTATION_HISTORY_ALTERED` | S-7 |
| R-21 | **Recalcul post-ADMISSION** : slot postérieur illisible (anomalie de contenu), après le Claim | le test de caractérisation `test_s4_*` **reste vrai** (B3 inchangé pour ce comportement) ; un **nouveau** test porte sur la fonction de neutralisation : `inventory_id` de la vue = identifiant de base ; anomalie consignée | S-7 |
| R-22 | Slot postérieur = répertoire, lien, erreur d'E/S, nom hors motif, trou de densité | blocage de sécurité, aucune neutralisation | S-7 |
| R-23 | **Portée forgée** : observation fournie par l'appelant / `AuthoritativeAdmission` construite à la main / chaîne du registre sans cette observation | non reconnue ; `TypeError` pour tout objet ou booléen fourni ; seule la relecture du registre fait foi | S-7, S-12 |
| R-24 | Vue F1 : ni assemblable ni persistable par B4/B5 (elle ne renvoie que des scalaires), refusée sans ADMISSION (elle relit le registre), AST : l'interprétation neutralisée ne sort pas de la fonction (voir R-71, R-72) ; variante `view_marker` (S-5b) : B5 refuse une interprétation marquée | type distinct, refus | S-7 (S-5b) |

### C. Chronologie et preuve de temps (modèle + états ; aucun vérificateur réel)
| ID | Cas | Attendu | Tranche |
|---|---|---|---|
| R-25 | **Preuve de temps absente** | `ABSENT` → niveau ≠ `PROSPECTIVE_ANCHORED` → `LEVEL_NOT_PROSPECTIVE_ANCHORED` | S-9 |
| R-26 | **Preuve mal ciblée** : empreinte = `commitment_content_hash` (engagement seul) | `INVALID` / `TIME_PROOF_NOT_OWN_RESERVATION` (jamais recevable, 23.6) | S-9 |
| R-27 | Preuve visant la réservation d'une autre campagne | `TIME_PROOF_NOT_OWN_RESERVATION` | S-9 |
| R-28 | `borne + marge > ws` ; marge absente ; marge ≤ 0 | `TIME_PROOF_ANCHORED_TOO_LATE` ; `UNVERIFIED` (E3-A F4) | S-9 |
| R-29 | **Preuve expirée / en attente / autorité hors liste / `genTime` illisible / révocation inconnue** | `UNVERIFIABLE` (et selon N12 pour la révocation) ; aucun artefact écrit | S-9 |
| R-30 | Certificat non valide à `genTime` ; revérification hors ligne au démarrage sans preuves de révocation conservées | `INVALID` / `UNVERIFIABLE` | S-9 |
| R-31 | `verification_result` = « VALID » dans le fichier mais preuve brute invalide | recalcul : `INVALID` (`R-REPLAY`) | S-9 |

### D. Autorisation
| ID | Cas | Attendu | Tranche |
|---|---|---|---|
| R-32 | **Autorisation absente** | prérequis d'`ADMISSION` non remplis (`AUTHORIZATION_MISSING`) | S-4, S-12 |
| R-33 | **Autorisation non correspondante** : autre attestation, autre `claim_id`, autre mode, autre fenêtre, autre code, autre projection | refus typé par champ | S-4 |
| R-34 | Une nouvelle attestation est publiée après l'autorisation, **avant l'`ADMISSION`** | l'autorisation ne vaut plus (l'attestation nommée n'est plus terminale : supersession, 23.29.3) ; après l'`ADMISSION`, voir R-49 | S-4, S-12 |

### E. Engagement, attachment, nullité, registre
| ID | Cas | Attendu | Tranche |
|---|---|---|---|
| R-35 | **Attachment divergent** : `commitment_content_hash`, plage, `ingestion_record_content_hash`, `attachment_id` (vecteur V7) | `ATTACHMENT_*` ; « toute inégalité l'invalide » | S-10 |
| R-36 | Seconde ingestion complète / second attachment | refusé (`…_DUPLICATE`), jamais choisi | S-10 |
| R-37 | **Engagement invalide** : hash recalculé ≠ stocké, fenêtre ≠ `plan.final_holdout`, SHA Git courant ≠ engagé, pré-enregistration divergente | `verify_commitment` lève un refus typé (le test du **publieur** de `RESERVATION` qui rappelle ce vérificateur à chaque tentative relève d'E3-J) | S-8 |
| R-38 | **Engagement nul + réservation conservée** : void avec réservation publiée | la `RESERVATION` reste, la fenêtre n'est plus utilisable ; void refusé si `CONSUMPTION`/`ReadIntent` existe ; ◇ suppression du fichier void non détectée par le registre | S-10 |
| R-39 | **Retour en arrière du registre** : témoin `head_seq = 7`, chaîne de tête 5 ; témoin avec hash différent au même `seq` ; ◇ perte de queue non témoignée | `REGISTRY_ROLLED_BACK` ; `REGISTRY_FORK` ; ◇ indétectable (limite 23.9) | S-11 |
| R-40 | **Reprise après crash** de chaque singleton / slot : orphelin temporaire, fichier absent, `PublishedUnconfirmed`, slot tronqué | complet-ou-absent ; `PublishedUnconfirmed` = binding ; aucune suppression, aucune réécriture | S-2, S-4 |

### F. Compatibilité et garde-fous transversaux
| ID | Cas | Attendu | Tranche |
|---|---|---|---|
| R-41 | B3 v4 : les noms E3-E sont informatifs (jamais exposants) ; un fichier inconnu reste inconnu ; un A0 v3 se relit en historique intègre ; `rules_digest` de v4 épinglé | conforme | S-5a |
| R-42 | **E3-A / E3-D inchangés** : vecteurs d'or d'E3-A (`inventory_id`, `classification_id`) et suite E3-D identiques avant/après | zéro diff | toutes |
| R-43 | **Aucun callback/booléen comme preuve** : chaque fonction publique avec un `bool`, un `Callable` ou un objet « vérifié » fourni | `TypeError` | S-12 |
| R-44 | AST : aucun module E3-E n'importe E2, `_append_record`, `os.remove`, `unlink`, `rmtree`, `shutil.rmtree` ; aucun écrivain public de `RESERVATION`/`ADMISSION` | conforme | toutes |
| R-45 | `mode == REAL` → refus (`MODE_REFUSED`) par chaque fonction qui lit le registre | conforme | S-3a, S-12 |
| R-46 | Garde de fixtures : aucun chemin de test ne désigne de données de marché ni le `FINAL_HOLDOUT` ; aucun module E3-E n'importe un chargeur de `S_H` | conforme | toutes |
| R-47 ◇ | Invariance d'étage : l'`inventory_id` recalculé à `RESERVED` et à `ADMITTED` est identique pour les mêmes faits (E3-A, `partition_own_records`) | égal (caractérisation vérifiée par la revue B) | S-3a, S-7 |
| R-48 | Deux attestations publiées concurremment (deux processus) | exactement une retient le slot ; l'autre devient non terminale ; aucune n'est réécrite | S-2, S-3a |
| R-49 | **Recontrôle pré-Claim (étape 11 bis)** : (a) déclaration durcissante, exposition étrangère, marge ou projection changées entre l'ADMISSION et le Claim ; (b) nouvelle attestation seulement | (a) `ADMITTED_STALE` terminal, **aucun Claim** ; (b) sans effet, consigné ; l'étape 13 post-Claim n'est jamais le premier contrôle | S-7 |
| R-50 | `attestation_seq` = `True` / `False` / chaîne / flottant ; `declaration_tip_seq` booléen | `ATTESTATION_INVALID` | S-2 |
| R-51 | Attestation **valide mais défavorable par valeurs connues** (`RETROSPECTIVE_EXPOSED`, `UNDETERMINED`, niveau ≠ `PROSPECTIVE_ANCHORED`) ; fait de chronologie **inconnu** (marge ou `s0_max_time_utc` absent) | lisible et historisée ; `ATTESTATION_NOT_ELIGIBLE` ; `ADMISSION` non publiable ; un fait inconnu rend l'attestation **non publiable** (clés 22–23 non nulles) | S-3a |
| R-52 | **Plusieurs autorisations** : seule celle épinglée par l'`ADMISSION` compte ; une ancienne autorisation d'une attestation périmée est sans effet et ne révoque rien | conforme | S-4, S-12 |
| R-53 | **Changement de marge** (configuration de root) ou de `s0_max_time_utc` entre l'attestation et l'`ADMISSION` | `ATTESTATION_STALE_MARGIN` / `…_S0` ; `chronology_facts_digest` explique le `classification_id` divergent | S-3b |
| R-54 | Nullité demandée alors qu'un **Claim sans `CONSUMPTION`** existe (C-17) | refusée (N14) | S-10 |
| R-55 | Première `RESERVATION` du registre (slot 0) convertie en finding de l'inventaire | acceptée (défaut `seq >= 1` corrigé) ; sans correction, le test échoue — il caractérise C-16 | S-0b |
| R-56 | Répertoires créés (`exposure/<inventory_id>/`) : durabilité du répertoire parent avant la première publication | exigée (E3-C) ; sinon refus RÉESSAYABLE | S-2 |
| R-57 | Rejeu d'un singleton après un échec **avant** `link` ; après `link` visible | avant : nouveau `created_at`, nouveau hash, permis ; après : aucun rejeu | S-2, S-4, S-8 |
| R-58 | Orphelin `.exposure.tmp.<32 hex>` à la racine de campagne | toléré par B3 v4 (règle d'orphelin imposée par B2) ; tout autre nom d'orphelin : inconnu, bloquant | S-5a |
| R-59 | Reconfirmation **courante** de la reprise : `PublishedUnconfirmedError` / `reconfirmation_reliable` faux **dans le processus qui reconfirme** ; ◇ un échec de `fsync` survenu dans un processus mort **n'est pas détectable** | décision humaine pour le premier cas ; le second est une limite documentée, jamais une garde | S-7 |
| R-60 | **Dossier de campagne copié après `CONSUMPTION`** présenté comme une reprise | refusé : `campaign_state == CONSUMED` ⇒ refus d'E3-J `AlreadyInProgressOrConsumed` (le nom `CAMPAIGN_ALREADY_CONSUMED` est celui de `find_reusable_record`, que la reprise n'appelle pas) ; test de contraste avec une lecture autoritative naïve | S-7 |
| R-61 | Témoin plus haut que la chaîne ; témoin au même `seq` avec un autre hash ; témoins locaux seuls ; ◇ omission du dernier témoin | `REGISTRY_ROLLED_BACK` (testé **avant** `FORK`) ; `REGISTRY_FORK` ; pas de preuve ; ◇ indétectable | S-11 |
| R-62 | Champs auto-déclarés de la preuve modifiés (`time_bound_utc`, `nonce_hex`, `trust_list_sha256`) avec hash recalculé | recalcul depuis la preuve brute : `INVALID` (`R-REPLAY`) | S-9 |
| R-63 | Attestation fondée sur `SYNTHETIC_FIXTURE` présentée à un registre `REAL` ; `time_proof_type` / `registry_mode` divergents du réel | refus (`MODE_REFUSED` / `ATTESTATION_INVALID`) | S-3a |
| R-64 | Neutralisation par **causes structurées** : deux campagnes de même `inventory_id` et de chemins identiques ne se confondent pas ; filtrage jamais par chaîne | conforme | S-5a, S-7 |
| R-65 | Lecture stricte des nouveaux artefacts : lien symbolique, fichier non régulier, taille > plafond, fichier qui grandit pendant la lecture | refus | S-2, S-4, S-8, S-9, S-10 |
| R-66 | **Un seul tampon** : fichier remplacé entre la vérification et le calcul du hash épinglé | refus (le hash épinglé provient des octets vérifiés) | S-3a |
| R-67 | Liste blanche AST des importeurs de `_append_record` (E3-D, E3-J réservé) ; aucun écrivain public d'`ADMISSION` hors de la future API vérifiante | conforme | S-12 |
| R-68 | **Durabilité des artefacts épinglés** : attestation, autorisation, engagement, preuve, attachment publiés par lien mais dont le répertoire n'est pas confirmé (crash simulé) | refus RÉESSAYABLE avant l'ADMISSION et à la reprise ; jamais `ADMITTED_ATTESTATION_MISSING` irréparable | S-3a, S-7 |
| R-69 | **Reprise sans reconstruction de candidat** : l'appel de reprise n'appelle ni `assemble_record` ni `find_reusable_record` avec un corps dérivé du disque courant | conforme (AST + comportement) | S-7 |
| R-70 | `publish_attestation` / `publish_authorization` quand l'état dérivé de la campagne est ≥ `ADMITTED` | refus `PUBLICATION_AFTER_ADMISSION` ; ◇ une écriture directe de fichier reste possible (détection par 11 bis) | S-2, S-4 |
| R-71 | `recompute_post_admission_view` : valeur de retour sans `created_at`, comptabilité, `inventory_content_hash`, ni dataclass B3/B4 ; `dataclasses.asdict` de la vue refusé par la relecture de B5 ; AST : aucune fonction n'exporte l'interprétation neutralisée ; copie/pickle de la vue sans effet sur B5 | conforme | S-7 |
| R-72 | `recompute_post_admission_view` sans ADMISSION, avec un `AuthoritativeAdmission` construit à la main, ou avec un étage fourni par l'appelant | `TypeError` / refus : la fonction relit le registre et dérive l'étage | S-7 |
| R-73 | **Décimaux** : grammaire (ni exposant, ni `+`, ni `-0`, ni zéros de fin), identité aller-retour `canon(float(s)) == s`, `"0.10000000000000001"` refusé, égalité exacte avec la valeur du fichier historique ; `"0.5\n"`, chiffres pleine chasse et `True` pour un champ `int` refusés ; V10 | conforme ; aucune conversion silencieuse | S-8 |
| R-74 | `10000` vs `10000.0` : hashs différents pour une même configuration ; un flottant dans un record publié par lien est refusé par `serialize_normative_json` | conforme (V10) | S-8 |
| R-75 | **Chaîne d'autorisations** : candidat = slot de plus haut `seq`, doit nommer l'attestation terminale ; aucun repli sur un slot plus ancien ; ré-autorisation après péremption ; après l'ADMISSION seule l'autorisation épinglée par hash compte ; slot postérieur illisible (contenu) neutralisé, slot antérieur illisible bloque | conforme | S-4, S-7 |
| R-76 | **Classes de refus** : échec d'E/S passager pendant la reconfirmation ou la lecture | RÉESSAYABLE, jamais `ATTESTATION_STALE_*` ; un fait différent = PÉREMPTION définitive ; une altération = SÉCURITÉ | S-3a, S-3b |
| R-77 | **B3 v4 minimal** : noms E3-E de la racine de campagne informatifs ; tout autre nom (`read_intent.json`, `validations/`, …) reste `UNKNOWN_SOURCE` ; digests RESULTS et SPLIT_PLAN_DIR **identiques** à v3 ; un A0 v2/v3 se relit en historique ; aucun champ ajouté à `SourceInterpretation` ; golden E3-A/B4/B5 inchangés | conforme | S-5a |
| R-78 | **C-16** : `RegistryRecordFact(seq=0)` accepté (`source_id` se termine par `/000000`), `seq=-1` refusé, `True`/`"1"` refusés (types) ; aucune identité d'inventaire existante ne change | conforme | S-0b |
| R-79 | **Claim sans `CONSUMPTION`** (crash entre l'étape 12 et 12 bis) : `campaign_state` reste `ADMITTED` | la reprise **n'exécute pas** 11 bis : refus `AlreadyInProgressOrConsumed` / `CLAIM_ONLY` à régulariser (23.18) ; ni recalcul, ni `ADMITTED_STALE`, ni Claim propre traité comme exposant non absorbé | S-7 |
| R-80 | **Péremption de l'autorisation** : après l'ADMISSION, une attestation postérieure **valide** ; avant l'ADMISSION, une attestation plus récente | après : l'autorisation épinglée par hash reste valable, 11 bis réussit ; avant : l'autorisation ne vaut plus (attestation non terminale) | S-4, S-7 |
| R-81 | **Décimaux, suite** : `"-0"` refusé (grammaire et `canon`), `{"decimal": "0"}` accepté, champ `decimal` reçu en `int` (et inversement) refusé, enveloppe d'ambiguïté documentée | conforme (V10) | S-8 |

Les cas R-49 à R-81 (révisions 2 à 5). **La colonne « Tranche » de cette matrice fait foi** ; la colonne « RED » du tableau des tranches ne liste que les cas principaux. Les cas R-49 à R-81 sont placés à la suite de la section F pour ne pas renuméroter ; leur groupe est indiqué par la tranche.

### Couverture de la liste de la mission
Hash correct/incorrect → R-01…R-05 · champs manquants/inconnus/altérés → R-06…R-12 · slot épinglé absent → R-15 · non terminal → R-16 · ajouté concurremment → R-17, R-18 · attestation historique modifiée → R-19, R-20 · recalcul post-ADMISSION → R-21, R-24 ·
engagement invalide → R-37 · preuve de temps expirée/absente/mal ciblée → R-25…R-31 · autorisation absente/non correspondante → R-32…R-34 · attachment divergent → R-35, R-36 · engagement nul et réservation conservée → R-38 · retour en arrière du registre → R-39 · reprise après crash → R-14, R-40, R-57, R-59, R-60. Ajouts de la révision 2 : recontrôle pré-Claim R-49, éligibilité R-51, supersession d'autorisation R-34/R-52, marge R-53, nullité après Claim R-54, défaut de slot 0 R-55, témoin R-61, preuve auto-déclarée R-62, mode R-63, causes structurées R-64, lecture stricte R-65, tampon unique R-66, importeurs R-67.

## 4. Critères de sortie de chaque tranche et de l'ensemble

- Tous les RED de la tranche ont échoué pour la bonne raison avant le GREEN ; la suite de régression (section 1.3) est verte ; deux revues indépendantes en lecture seule sont corrigées ; mutation ciblée (survivants expliqués un à un, jamais présumés inoffensifs) ; validation Linux si E/S de système de fichiers.
- **Verdict d'ensemble E3-E** : au mieux `E3-E PARTIALLY READY / SPEC BLOCKED` tant que S-7 (F1) n'est pas débloquée et tant que les vérificateurs RFC 3161/OpenTimestamps (23.24) et E3-F manquent. `REAL` reste désactivé quel que soit le résultat.
