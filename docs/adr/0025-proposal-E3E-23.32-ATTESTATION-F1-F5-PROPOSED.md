# Proposition CONSOLIDÉE d'addendum ADR 0025 § 23.32 — attestation (F5), chronologie des attestations (F1), autorisation, décimaux, recontrôle pré-Claim — NON NORMATIVE, NON ADOPTÉE

**Statut : PROPOSITION (2026-10-20), révision 6 (corrigée après six revues indépendantes : `0025-proposal-E3E-REVIEWS.md`). Aucune règle de ce fichier n'est en vigueur.** Le texte d'autorité reste `docs/adr/0025-gate-v-validation-policy-v1.md` (addenda 23.27 à 23.31). Ce fichier ne devient normatif que par une décision explicite de l'utilisateur sur la
matrice `0025-proposal-E3E-N1-N20-FINAL-MATRIX.md`, suivie de son intégration dans l'ADR sous le numéro 23.32. Il remplace comme document de travail les sections 1.3 et 2.2 de `0025-proposal-E3B-F1-F5-PROPOSED.md` (qui reste en place, historique). Il ne modifie aucune formule d'E3-A, aucune identité historique, aucun code publié.

`REAL` = DISABLED / NOT QUALIFIED · `GATE V` = NON PASSÉE · `FINAL_HOLDOUT` = NON ACCÉDÉ · `F1` = **SPEC BLOCKED** tant que N4, N5, N6, N7 et N19 ne sont pas acceptées · `F5` = **PROPOSED**.
Étiquettes : **ACCEPTED** (écrit dans l'ADR, section citée) · **PROPOSED** (ce document) · **BLOCKED** (décision, valeur opérationnelle de 23.24 ou composant absent). Vecteurs : `0025-proposal-E3E-HASH-VECTORS.json` (script stdlib sans import du dépôt, recalculés indépendamment par six relecteurs, recoupés avec la recette d'E3-A).

---

## 23.32.0 — Principes (PROPOSED)

1. **Un hash prouve l'intégrité, pas l'authenticité ni le temps.** Il détecte une altération **qui ne recalcule pas les hashs** ; un acteur qui peut écrire des fichiers *et* recalculer les hashs n'est arrêté ni par eux ni par la chaîne du registre (tant qu'aucun témoin de tête hors hôte n'existe) : sa limite est celle des permissions du compte de service (23.9). L'identité de l'attestant et de l'autorisant est déclarative (23.11, dernier alinéa).
2. **Aucun objet vérifié ne se transmet par valeur.** Une fonction qui vérifie un artefact le **relit sur disque** (`R-REREAD`). Un booléen, un callback, une instance de dataclass construite par l'appelant (`AuthoritativeAdmission` en est constructible par n'importe qui) ou un « témoin » n'est jamais une preuve (`R-NOBOOL`).
3. **Un seul tampon par vérification (`R-ONEBUFFER`).** Les octets vérifiés sont ceux dont on tire le hash épinglé. Toute lecture reprend `read_strict_file` (B5) : `lstat`, ouverture sans suivre de lien, fichier régulier, taille bornée avant lecture, stabilité.
4. **Échec fermé, trois classes de refus** : **SÉCURITÉ** (intégrité ou authenticité non établie, artefact altéré/inconnu/rompu), **PÉREMPTION** (un *fait* ou un contenu a changé : définitive), **RÉESSAYABLE** (échec d'E/S passager, durabilité non confirmée : aucune conclusion, rien n'est consommé). Un échec d'E/S n'est jamais une péremption (revue D, constat 8).
5. **Aucune suppression de preuve** : les anomalies neutralisées sont consignées dans l'audit.
6. **Mode** : tout est spécifié pour `SYNTHETIC` ; un registre `REAL` reste refusé (E3-D). Aucune règle ne qualifie `REAL`.
7. **Plafonds de taille** : provisoires et non normatifs (comme 23.31.5), valeurs = décision 23.24.
8. **Durabilité des artefacts épinglés** : avant l'`ADMISSION` et à toute reprise, chaque artefact épinglé publié par lien (attestation, autorisation, engagement, preuve de temps, attachment) est **reconfirmé** (`confirm_published_slot` avec son SHA-256 attendu) ; non confirmé ⇒ refus RÉESSAYABLE (revue D, constat 3).

---

## 23.32.1 — Schéma de l'attestation (F5) — PROPOSED

`gate_v_exposure_attestation_v1` (nom ACCEPTED, 23.13), record JSON **plat** dans `<campaign_dir>/exposure/<inventory_id>/attestation_<seq4>.json` (chemin ACCEPTED, 23.29.3). **32 clés exactes**, toutes obligatoires, aucune autre ; aucune valeur `null`, aucun flottant, aucun booléen là où un entier est attendu.

| # | Clé | Type | Origine / contrôle |
|---|---|---|---|
| 1 | `version` | texte | `gate_v_exposure_attestation_v1` (sépare les domaines) |
| 2 | `campaign_id` | texte | campagne attendue (23.31.1) |
| 3 | `inventory_id` | hex64 | = nom du répertoire (23.29.3) ; identité scientifique (23.27.3) |
| 4 | `attestation_seq` | entier 1..9999 | = nom du slot |
| 5 | `inventory_content_hash` | hex64 | A0 **persisté** attesté, relu par hash (23.27.3) |
| 6 | `inventory_content_digest` | hex64 | digest d'`{inventory_id, trial_accounting}` (23.27.3) |
| 7 | `static_sources_digest` | hex64 | ensemble pertinent (23.10) |
| 8 | `overlap_projection_hash` | hex64 | projection (23.10) |
| 9 | `declaration_tip_seq` | entier 1..9999 | sommet de la chaîne **terminale** (23.29.3) |
| 10 | `declaration_tip_content_hash` | hex64 | `declaration_content_hash` du sommet |
| 11 | `declaration_lineage_digest` | hex64 | digest de lignée (23.29.2) |
| 12 | `commitment_id` | texte | engagement (23.4) |
| 13 | `commitment_content_hash` | hex64 | engagement (23.4) |
| 14 | `attachment_id` | texte | attachment (23.8) |
| 15 | `attachment_content_hash` | hex64 | attachment (23.8) |
| 16 | `time_proof_content_hash` | hex64 | `ReservationTimeProof` (23.6) |
| 17 | `time_proof_type` | texte | `proof_type` de la preuve (une attestation fondée sur `SYNTHETIC_FIXTURE` est reconnaissable) |
| 18 | `registry_mode` | texte | mode du registre à l'attestation (`SYNTHETIC`) |
| 19 | `registry_id` | texte | registre logique (23.9) |
| 20 | `registry_prefix_seq` | entier ≥ 0 | tête du préfixe épinglé (le registre numérote depuis 0) |
| 21 | `registry_prefix_content_hash` | hex64 | `record_content_hash` de ce slot |
| 22 | `anchor_margin_seconds` | entier (non booléen, de tout signe : ≤ 0 est jugé `UNVERIFIED` par E3-A F4) | marge d'ancrage lue dans la configuration de root (23.24) |
| 23 | `s0_max_time_utc` | instant UTC normalisé | `max(time)` de `S0`, fourni par E3-J |
| 24 | `chronology_facts_digest` | hex64 | SHA-256 du JSON canonique des **7 faits de chronologie d'E3-A** (`_chronology_record`), calculé (V1) |
| 25 | `classification_rules_version` | texte | `gate_v_exposure_classification_v1` |
| 26 | `classification_id` | hex64 | classification **recalculée** (E3-A) |
| 27 | `classification` | texte (énumération E3-A) | redondant avec 26 |
| 28 | `chronology_level` | texte (énumération E3-A) | « inscrit dans l'attestation » (23.11 étape 3) |
| 29 | `own_record_stage` | texte | `RESERVED` |
| 30 | `attestor` | texte | identité **déclarative**, nominative |
| 31 | `created_at` | instant UTC normalisé | **injecté** (aucune horloge dans un module de modèle) ; pas une preuve de date |
| 32 | `attestation_content_hash` | hex64 | hash de contenu (23.32.2) — **seule clé hors préimage** |

Pas d'`attested_at` (un seul horodatage déclaratif) ni d'`attestation_id` sémantique (N16).
**Textes** : NFC, non vides après `strip()`, 256 points de code au plus, aucun point de code de catégorie `Cc`, `Cf`, `Cs`, `Co`, `Zl`, `Zp` ; `Cn` n'est pas utilisée (dépend de la version de la base Unicode) ; clés des objets hachés en ASCII. Un texte NFD ou contenant un tel point de code est refusé (`ATTESTATION_INVALID`), jamais normalisé en silence.

## 23.32.2 — Hash de contenu, canonicalisation (F5) — PROPOSED

```
attestation_content_hash = SHA-256( UTF-8( canonical_json( record privé de la seule clé "attestation_content_hash" ) ) )
canonical_json(x)        = json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)      # Décision 20.3
```
Sans autoréférence ; indépendant de l'ordre d'insertion des clés et de la valeur de la clé exclue (V3, V4) ; `ensure_ascii=True` ou NFD donnent un autre hash (contre-vecteurs V2) ; `version` dans la préimage ; octets persistés = sérialiseur normatif de 23.29.4 avec point fixe (V9 : SHA-256 des octets persistés = `pinned_file_sha256`). Toute évolution de la préimage change `version` ; version connue antérieure = lecture historique intègre (comme 23.31.6) ; version inconnue = `ATTESTATION_VERSION_UNKNOWN`.
Alternative écartée (N1-b) : SHA-256 des octets du fichier (second type de référence, abandon de l'alignement avec A0 et déclaration) ; ce SHA-256 d'octets reste utilisé *dans l'observation* (23.32.5).

## 23.32.3 — Publication et relecture — PROPOSED

- **Publication** : `publish_json_by_link` d'E3-C avec `TempNaming.EXPOSURE` (existant ; **aucune modification d'E3-C**), jamais de repli sur `O_EXCL`. Slots denses depuis `0001`, jamais écrasés ni supprimés. La fonction de publication relit la chaîne terminale, calcule `attestation_seq` et le hash, publie ; sur `SlotOccupiedError`, **retour à la relecture et reconstruction complète** ; tentatives bornées et fournies (aucun défaut). Durabilité du répertoire parent exigée avant la première publication.
- **Refus de publier après l'ADMISSION** : `publish_attestation` (et `publish_authorization`, et tout futur éditeur de déclarations) **refuse** si l'état dérivé de la campagne est au moins `ADMITTED` (`PUBLICATION_AFTER_ADMISSION`). Ce n'est pas une barrière (un fichier peut toujours être écrit hors de cette API) : c'est de l'hygiène pour que le chemin normal ne fige pas une campagne par erreur ; la détection reste celle de 23.32.6.4–6.5.
- **Crash** (matrice de 23.10) : orphelin inoffensif ; `link` sans `fsync` de répertoire = `PublishedUnconfirmed` (slot binding). Un rejeu après un échec **avant** `link` utilise un nouveau `created_at`, donc un nouveau hash (permis) ; après `link` visible, aucun rejeu.
- **Relecture** (ordre fixe, échec fermé) : octets stricts → jeu de clés exact → types stricts → `version` connue → hash recalculé → point fixe → répertoire = `inventory_id` → slot = `attestation_seq` → `campaign_id`.

## 23.32.4 — Vérification d'une attestation (avant l'ADMISSION) — PROPOSED

Valide si, dans l'ordre et **sur relectures faites pendant la vérification** (`R-ONEBUFFER`) : relecture 23.32.3 ; slot de plus haut `seq` de la chaîne **terminale** (23.29.3, sans repli) ; `registry_mode` et `time_proof_type` égaux à ceux relus (`SYNTHETIC_FIXTURE` refusé en `REAL`) ; A0 relu par hash, `inventory_id` et `inventory_content_digest` égaux ; A0′ recalculé à neuf égal sur `inventory_id`, `static_sources_digest`, `overlap_projection_hash`, `inventory_content_digest` (23.27.3) ; tête de la chaîne terminale et `declaration_lineage_digest` égaux ; engagement, attachment, preuve de temps relus, hashs égaux et cohérents (23.32.8) ; `registry_prefix_content_hash` = slot `registry_prefix_seq` de la chaîne courante, `registry_prefix_seq` ≥ `seq` de la `RESERVATION` propre ; faits de chronologie recalculés (23.32.4 bis) ; classification recalculée à l'étage `RESERVED` égale `classification_id`, `classification`, `chronology_level`.
**Éligibilité** : `admission_refusals(classification)` vide (classe `FRESH_UNEXPOSED_DECLARED`, niveau `PROSPECTIVE_ANCHORED`) ; une attestation valide mais défavorable reste lisible et historisée sans rendre l'`ADMISSION` publiable (`ATTESTATION_NOT_ELIGIBLE`). Les déclarations ne font que durcir (23.11) : `RETROSPECTIVE_EXPOSED` ne redevient pas `FRESH` dans une chaîne ; `UNDETERMINED` ne devient favorable que si des faits changent.
**Refus** (noms PROPOSÉS ; les trois premiers existent déjà) : `ATTESTATION_INVALID`, `ADMITTED_ATTESTATION_MISSING`, `ADMITTED_ATTESTATION_REPLACED`, `ATTESTATION_VERSION_UNKNOWN`, `ATTESTATION_NOT_TERMINAL_SLOT`, `ATTESTATION_CAMPAIGN_MISMATCH`, `ACCOUNTING_CHANGED` (ACCEPTED, 23.27.3), `ATTESTATION_STALE_{INVENTORY, STATIC_SOURCES, PROJECTION, DECLARATIONS, LINEAGE, REGISTRY_PREFIX, CLASSIFICATION, COMMITMENT, ATTACHMENT, TIME_PROOF, MARGIN, S0}`, `ATTESTATION_NOT_ELIGIBLE`, `ATTESTATION_NOT_PUBLISHABLE`. Péremption = **nouvelle attestation et nouvelle autorisation humaines** (23.27.4, ACCEPTED), jamais une réparation.

### 23.32.4 bis — Dérivation des faits de chronologie (`ChronologyFacts` d'E3-A)
| Fait | Source | Relu par | Épinglé |
|---|---|---|---|
| `commitment_t_sel_utc` | `t_sel_utc` de l'engagement | E3-E | via `commitment_content_hash` |
| `reservation_durable` | reconfirmation du slot `RESERVATION` ; échec d'E/S ⇒ **RÉESSAYABLE**, pas péremption | E3-E | via `registry_prefix_*` |
| `time_proof` | **recalcul** depuis la preuve brute et la liste de confiance (`R-REPLAY`) | E3-E | via `time_proof_content_hash`, `time_proof_type` |
| `anchor_margin_seconds` | configuration de root (23.24), lecteur typé fourni par E3-J | E3-J | **clé 22** (`ATTESTATION_STALE_MARGIN`) |
| `s0_max_time_utc` | calculé par E3-J sur `S0` (donnée de recherche, lue avant le Claim, 23.5) | E3-J | **clé 23** (`ATTESTATION_STALE_S0`) |
| `ingested_at_utc`, `ingestion_range_matches` | `IngestionRecord` désigné par l'attachment (E3-F, BLOCKED) | E3-E via `IngestionRecordRef` | via `attachment_content_hash` |

E3-E ne vérifie pas indépendamment la marge ni `max(time)` ; il vérifie qu'elles n'ont **pas changé**. Un fait inconnu est admis dans le record de faits (sa préimage) mais les clés 22–23 sont non nulles : marge ou `max(time)` inconnus ⇒ `ATTESTATION_NOT_PUBLISHABLE`.

## 23.32.5 — Référence portée par l'ADMISSION d'E3-D (sans modifier E3-D) — PROPOSED

`attestation_hash` = `attestation_content_hash` ; `authorization_hash` = `authorization_content_hash` ; `attestation_observation` = objet plat de **7 clés** (386 octets normatifs ; plafonds E3-D : 16 384 octets, profondeur 8) :
`version` (`gate_v_attestation_observation_v1`), `inventory_id`, `pinned_seq`, `highest_seq_observed` (**= `pinned_seq`** à la publication), `pinned_file_sha256` (SHA-256 des octets du slot ; alimente l'épinglage provisoire de B6, V9), `history_digest` = SHA-256(JSON canonique de `[{"seq": i, "file_sha256": h_i}]` pour `i = 1..highest_seq_observed`, V5), `slot_count`. Les trois champs `pinned_seq` / `highest_seq_observed` / `slot_count` sont volontairement redondants (contrôle de densité).
Cette section **ratifie** les choix P9 (conteneur opaque borné `attestation_observation`) et P13 (noms `attestation_hash`, `authorization_hash`, …) de la matrice E3-D, qui sont PROPOSED et non ACCEPTED.
**Ne prouve pas que l'observation soit vraie** : elle est écrite par le processus d'admission (E3-J). La chaîne de hashs d'E3-D détecte l'altération d'un enregistrement sans réécriture cohérente de la queue ; elle n'empêche pas un acteur qui peut écrire le registre de réécrire la queue en recalculant, tant qu'aucun témoin de tête hors hôte n'existe (23.9).

## 23.32.6 — F1 : attestation épinglée, recontrôle pré-Claim, slots postérieurs, reprise — PROPOSED, SPEC BLOCKED jusqu'à N4–N7 et N19

### 23.32.6.1 Source autoritative
L'enregistrement `ADMISSION` d'une chaîne **entière et vérifiée**, lu par `read_authoritative_admission` (barrière après lecture, reconfirmation du slot, `campaign_state`). Aucune portée, aucun slot, aucun hash fournis par un appelant n'est reconnu.

### 23.32.6.2 Construction de l'observation (fabrique de corps, appelée à chaque tentative)
(1) relire la chaîne du registre ; (2) vérifier l'attestation candidate et tous les prérequis (23.32.4, A0′, autorisation, preuve de temps, durabilité des artefacts épinglés : principe 8) ; (3) **double lecture stabilisée** du répertoire de la chaîne terminale (dernière E/S avant le retour du corps), identique sinon `ATTESTATION_UNSTABLE` ; (4) densité 1..n, tous lisibles ; (5) `pinned_seq == highest_seq_observed` ; (6) construire l'observation. Sur `SlotOccupiedError` : retour à (1), tout est reconstruit.

### 23.32.6.3 Sémantique : « postérieur à l'observation », et pourquoi aucune garde de blocage n'est retenue (décision N4)
Un slot `seq > pinned_seq` est absent de l'observation ; aucune date n'est utilisée (23.6). Un slot écrit entre la dernière lecture et le `link` est indiscernable d'un slot écrit après ; cette fenêtre est irréductible sans horloge commune.
**La validité d'une attestation porte sur l'ÉTAT (les faits), non sur l'intention de son auteur.** Après l'ADMISSION, l'attestation est fixée **par hash** ; tant que les faits attestés sont inchangés, une attestation postérieure n'apporte aucune information scientifique. Aucune sémantique de **révocation** n'existe dans l'ADR : le retrait volontaire passe par `CommitmentVoidRecord` (avant le Claim). La révision 3 (garde `PCG` bloquante, option A) est **abandonnée** : (i) elle amendait 23.10/23.29.3 (« un slot postérieur n'est pas un remplacement ») pour peu de gain ; (ii) elle ne couvrait que les attestations (une *déclaration* durcissante publiée entre l'ADMISSION et le Claim échappait à son observation) ; (iii) elle créait un état terminal hors de la liste fermée de 23.18 ; (iv) elle offrait à tout écrivain du dossier un levier de gel. **Option retenue (C)** : voir 23.32.6.4.

### 23.32.6.4 Recontrôle pré-Claim — « étape 11 bis » de 23.17 (amendement ADDITIF) — PROPOSED, N4
Après l'`ADMISSION` durable et **avant tout appel d'E2**, E3-J : (a) vérifie **d'abord** qu'**aucun Claim ni `ReadIntent` local n'existe** (étage dérivé par E3-J du registre + Claim + `ReadIntent` ; `campaign_state` d'E3-D ne couvre que la `CONSUMPTION` : un Claim sans `CONSUMPTION` reste `ADMITTED`) — sinon refus `AlreadyInProgressOrConsumed` (23.10) ou état `CLAIM_ONLY` à régulariser (23.18), **sans recalcul ni `ADMITTED_STALE`** — puis relit l'`ADMISSION` (23.32.6.1) et exige `campaign_state == ADMITTED` ; (b) exécute les contrôles **1, 3, 4, 5, 6 et 7** de 23.27.4 (le contrôle 2, comptabilité, est exclu : 23.27.3) sur l'attestation et l'autorisation **épinglées par hash** (jamais « les plus récentes ») ; (c) relit le slot épinglé (`pinned_file_sha256`, `attestation_hash`) et recalcule `history_digest` ; (d) reconfirme la durabilité des artefacts épinglés (principe 8) ; (e) recalcule l'`inventory_id` par la vue F1 (23.32.7) si des anomalies d'attestation postérieures existent.
- Changement d'un *fait* (contrôles 1, 3, 4 : exposition, ensemble pertinent, projection ; 5 : déclarations, classification ; 6 : autorisation — `claim_id`, mode, code ; 7 : préfixe ; marge) ⇒ PÉREMPTION ⇒ `ADMITTED_STALE`, aucun Claim consommé. **Amendement de 23.10 étape 8 / 23.18** : 23.10 ne définit `ADMITTED_STALE` que pour un changement de `static_sources_digest` ; la proposition l'étend à tout échec de fait de 11 bis. L'état est **dérivé et recalculé à chaque tentative** (23.18 : états dérivés des artefacts présents) : le consigner dans l'audit n'en fait **pas** une garde, et une valeur rétablie (une marge, par exemple) peut le faire disparaître. Le rendre réellement terminal exigerait un marqueur **persisté** : amendement distinct, **non proposé ici**. Seule une décision humaine déclare la campagne nulle. Contenu altéré du slot épinglé ou de l'historique ⇒ refus de SÉCURITÉ, aucun Claim. Échec d'E/S ⇒ RÉESSAYABLE.
- Les slots `seq > pinned_seq` restent **sans effet** (23.29.3 inchangé), consignés `ATTESTATION_WITHOUT_EFFECT`.
- **Gain réel** : aujourd'hui aucun contrôle de *faits* n'existe entre l'ADMISSION (étape 11) et l'étape 13 (l'étape 8 de 23.10 ne compare que `static_sources_digest` et la projection), qui est *postérieure au Claim* et annule alors une exécution dont le droit est déjà consommé ; 23.27.3 n'exige en reprise que `inventory_id`, `static_sources_digest` et la projection (« **seuls** ») : l'étape 11 bis **amende** 23.27.3 (contrôles 1, 3, 4 conservés ; 5, 6, 7 ajoutés) et l'étend au chemin nominal (aujourd'hui seule l'étape 8, qui ne compare que `static_sources_digest` et la projection).
- **Comparaison formelle A / B / C** (matrice N4) : A bloque toute attestation postérieure (levier, état hors 23.18, couverture partielle) ; B applique 23.29.3 à la lettre sans recontrôle (Claim irréversible possible sur des faits changés) ; **C** protège les faits sans nouveau levier ni état terminal.
- **Abandon sélectif** : ne pas lancer le Claim reste toujours possible et est compté (réservation abandonnée, 23.8/23.27.5) ; aucune information sur le holdout n'existe avant le Claim, donc aucune sélection fondée sur un résultat. C n'ajoute aucun levier : un durcissement de déclaration annulait déjà l'exécution à l'étape 13 (après le Claim) ; 11 bis l'arrête **avant** le Claim.

### 23.32.6.5 Slots après l'ADMISSION, et reprise (décision N7)
| Slot du répertoire de la chaîne terminale | Traitement |
|---|---|
| `seq < pinned_seq` | doit égaler son entrée de l'historique, sinon `ADMITTED_ATTESTATION_HISTORY_ALTERED` (SÉCURITÉ) |
| `seq == pinned_seq` | octets = `pinned_file_sha256` ET record = `attestation_hash` (`…_MISSING` / `…_REPLACED` / `ATTESTATION_INVALID`) |
| `seq > pinned_seq`, lisible | sans effet, consigné |
| `seq > pinned_seq`, anomalie de **contenu** (JSON invalide, tronqué, clé dupliquée, constante non finie, BOM, UTF-8, substitut isolé, profondeur, taille, type) | **neutralisé pour le calcul scientifique seulement**, consigné |
| `seq > pinned_seq`, répertoire / lien / erreur d'E/S / nom hors motif / trou de densité | bloque (SÉCURITÉ) |
| autre chaîne d'`exposure/` que la terminale | changement d'exposition (23.29.3) |
| fichier inconnu, déclaration altérée, rupture de chaîne | bloque |
| slot d'autorisation | voir 23.32.8 |

**Reprise (`R-RECOVERY`, révision 5).** Elle exige d'abord **qu'aucun Claim ni `ReadIntent` local n'existe** (E3-J, BLOCKED : le registre ne voit pas le Claim) ; avec un Claim sans `CONSUMPTION` la reprise est refusée (`AlreadyInProgressOrConsumed`, ou `CLAIM_ONLY` à régulariser), jamais traitée comme `ADMITTED_STALE`. Elle **continue** l'`ADMISSION` existante : `read_authoritative_admission` (barrière, reconfirmation ; `campaign_state` exigé `ADMITTED`) puis l'étape 11 bis sur les artefacts **épinglés**. **Elle ne reconstruit aucun candidat à partir de l'état courant du disque** (un candidat porterait l'attestation « la plus haute » et ne pourrait pas égaler `admission_id` : `CAMPAIGN_ALREADY_REGISTERED`). `find_reusable_record` (E3-D, inchangé) ne sert qu'à rejouer une *publication* dans la même tentative. **Si une ADMISSION existe déjà pour la campagne, toute nouvelle tentative passe par cette voie de reprise** (jamais `find_reusable_record` seul, qui contournerait 11 bis) ; sinon la nouvelle tentative construit son candidat en direct et reçoit `CAMPAIGN_ALREADY_REGISTERED` si l'ADMISSION diffère. Si la reconfirmation **courante** lève `PublishedUnconfirmedError`, décision humaine (un échec de `fsync` d'un processus mort n'est pas détectable : limite assumée).

### 23.32.6.6 Limites de `history_digest` (formulation honnête)
Il détecte, **après** la publication de l'ADMISSION, la modification d'un slot `1..pinned_seq` par un acteur qui ne réécrit pas aussi l'ADMISSION. Il ne détecte ni une modification antérieure à l'observation, ni une observation fausse mais cohérente, ni une queue du registre réécrite de façon cohérente.

## 23.32.7 — Vue de recalcul après ADMISSION, non persistable (décision N19) — PROPOSED

Fonction `recompute_post_admission_view` (module dédié, hors B3/B4/B5) qui :
1. **relit elle-même** le registre : elle reçoit `registry_root` et `campaign_id`, jamais un objet d'admission ; sans ADMISSION elle lève (aucune utilisation avant l'ADMISSION) ;
2. **relance elle-même** l'interprétation de B3 (`interpret_audit_roots`) à partir des racines d'audit de la configuration de root — elle ne reçoit **pas** une `SourceInterpretation` par valeur (`R-REREAD`) — et refuse `hooks_used` (propriété de `SourceInterpretation` que E3-J doit refuser) ; elle reçoit les mêmes autres entrées que le calcul de l'ADMISSION (vue de registre, étiquettes de racines dérivées, `AccountingViews`, contexte propre, label de la racine de la campagne courante) ; l'**étage exact** est dérivé par E3-J des artefacts persistés (registre + Claim + `ReadIntent`), jamais affirmé par l'appelant : c'est un **raffinement déclaré** de l'orientation 9 du 2026-10-19 (« étage propre exact fourni ») ; `limits` et la fenêtre de `interpret_audit_roots` viennent de la configuration de root et de l'ADMISSION, jamais de l'appelant ; l'appel interne passe `hooks=None` explicitement (le refus de `hooks_used` serait vacuant sinon) ;
3. retire de `incomplete_reasons` **exactement** les raisons `INFORMATIVE_UNRESOLVED:<root_label>/<relative_path>` produites par des **observations de scan** (`scans[*].scan.observations`) de règle `campaign.exposure.attestation` seulement, racine de la campagne courante, anomalie de **contenu**, `seq` > épinglé — les labels de racine étant uniques (`DUPLICATE_ROOT_LABEL`), la raison se dérive sans ambiguïté ; **aucun champ n'est ajouté à B3** (revue D, constat 6 : `incomplete_causes` est supprimé) ; un test d'équivalence épingle la formule des raisons de B3 ;
4. construit en interne une interprétation neutralisée (`dataclasses.replace`, qui doit aussi fixer `complete` pour satisfaire `__post_init__`), la passe à `assemble_exposure_inventory` (B4) **à l'intérieur de la fonction** et n'en tire que `inventory_id`, `static_sources_digest`, `overlap_projection_hash` ;
5. **ne renvoie que des scalaires** : `PostAdmissionRecomputeView(inventory_id_view, static_sources_digest, overlap_projection_hash, post_admission_anomalies)`. **L'interprétation neutralisée et l'assemblage ne quittent jamais la fonction** : il n'existe aucun objet persistable.

**Pourquoi c'est démontrable** : (persistance) aucun objet compatible B4/B5 n'est renvoyé ; (réutilisation avant ADMISSION) l'appel sans ADMISSION lève ; (contamination d'identités) les trois valeurs ne sont consommées qu'aux étapes 11 bis et 13, aucune formule d'E3-A/B4/B5 ne les reçoit, et les tests d'or de ces modules sont inchangés ; (copie/sérialisation) la vue ne contient ni `created_at`, ni comptabilité, ni `inventory_content_hash` ; ses clés ne sont pas celles d'un A0 (B5 la refuse à la relecture). **Limite honnête** : un code malveillant qui rejoue les étapes 2 à 4 à la main produit un assemblage authentique : aucun mécanisme local ne l'empêche.
**Écarts déclarés aux orientations du 2026-10-19** : (i) orientation 1 (« vue de recalcul **pure** ») : la fonction est **sans effet de bord** (lecture seule, aucune écriture) mais relit le registre et les racines (`R-REREAD`) : elle n'est donc pas pure au sens fonctionnel ; (ii) orientation 9 (« étage fourni ») : l'étage est **dérivé** par E3-J ; (iii) **aucune extension** de la neutralisation aux slots d'autorisation (orientations 4 et 6 : seules les attestations postérieures sont neutralisables).
**Durcissement optionnel (N19b, S-5b)** : champ additif `view_marker: Optional[str] = None` de `SourceInterpretation` (positionnel-compatible, hors `rules_digest`) posé par la fonction sur son `replace`, et garde de B5 sur le modèle de `hooks_used` ; protège contre la persistance **accidentelle** d'une interprétation marquée copiée ; exige une modification additive de B3 et B5 ; **non requis** pour N19.

## 23.32.8 — Autorisation humaine : contrat complet (décision N10) — PROPOSED

`gate_v_acquisition_authorization_v1` (nom ACCEPTED, 23.13), **20 clés exactes** : `version`, `campaign_id`, `authorization_seq`, `attestation_inventory_id`, `attestation_seq`, `attestation_content_hash`, `commitment_id`, `commitment_content_hash`, `claim_id`, `window_start_utc`, `window_end_utc`, `mode`, `code_identity_hash`, `qualification_report_hash`, `overlap_projection_hash`, `registry_prefix_seq`, `registry_prefix_content_hash`, `authorizer`, `created_at`, `authorization_content_hash` (recette de 23.32.2 ; V6). `qualification_report_hash` est `null` **seulement** en `SYNTHETIC` (en `REAL`, hash obligatoire : E3-Q, BLOCKED).
**Chaîne de slots** `<campaign_dir>/acquisition_authorization_<seq4>.json` (racine de campagne, denses depuis `0001`, publiés par lien, jamais écrasés ni supprimés) — **amende le nom de fichier unique de 23.13**. Règles :
- **Autorisation initiale** : slot `0001` nommant (par hash) l'attestation terminale.
- **Ré-autorisation** : nouveau slot (seq+1) nommant la nouvelle attestation terminale après une péremption (23.27.4 : « nouvelle attestation **et** nouvelle autorisation ») ; les anciens slots sont de l'historique **sans effet**, sans révoquer ni réactiver rien.
- **Candidat avant l'ADMISSION** : le slot de **plus haut `seq`** (plafond 9999) ; il doit nommer l'attestation terminale (hash, préfixe et projection égaux à ceux de l'attestation, `claim_id` calculable depuis le plan, mode, code) ; sinon `AUTHORIZATION_MISSING` / `AUTHORIZATION_MISMATCH` — **aucun repli sur un slot plus ancien**, aucune sélection implicite. Un trou de densité ou un slot illisible **avant** l'ADMISSION ⇒ `AUTHORIZATION_CHAIN_INVALID` (échec fermé, comme pour les attestations). `registry_prefix_seq` est un entier ≥ 0.
- **Après l'ADMISSION** : seule l'autorisation dont le hash est dans `authorization_hash` compte (trouvée par hash ; absente ⇒ `ADMITTED_AUTHORIZATION_MISSING`). Slots de `seq` supérieur : lisibles = sans effet, consignés ; **toute anomalie** (illisible, répertoire, lien…) **bloque** — conformément aux orientations 4 et 6 du 2026-10-19 (« les autres écritures locales postérieures annulent toujours ») ; l'extension de la neutralisation aux slots d'autorisation est une **option de N6, non retenue**. Slots de `seq` inférieur illisibles : bloquent.
- **Immutabilité / crash** : publication par lien (`PublishedUnconfirmed` binding) ; reconfirmation avant l'ADMISSION (principe 8).
- **Révocation ou refus** : **aucun enregistrement de retrait en V1**. Refuser = ne pas autoriser. Retirer avant l'ADMISSION = publier une nouvelle attestation (supersession). Retirer entre l'ADMISSION et le Claim = `CommitmentVoidRecord`. Après le Claim : impossible.
- **Péremption** : pas d'expiration par horloge (aucune horloge). **Avant l'ADMISSION**, l'autorisation cesse de valoir dès que l'attestation nommée n'est plus la **terminale**, ou que préfixe, projection, `claim_id`, mode ou code diffèrent. **Après l'ADMISSION**, elle est évaluée **par hash** (attestation épinglée) : une attestation postérieure, même valide, ne l'invalide pas ; le contrôle 6 de 23.27.4 compare les champs épinglés aux valeurs courantes (préfixe : « est toujours un préfixe de la chaîne »).
- **Aucune voie d'autorisation implicite** : une attestation, un hash bien formé, une vue du registre `SYNTHETIC` ou une ADMISSION n'autorisent rien ; l'ADMISSION exige `authorization_hash` ; sans slot valide, E3-E refuse.
**Alternative (fichier unique de 23.13)** : ré-autorisation impossible ; toute péremption, même avant l'ADMISSION, fait perdre la fenêtre (RESERVATION permanente) — rejetée comme disproportionnée.
**Tableau des autorités** (aucune ne se déduit d'une autre) : attestation = classification recalculable, aucun droit ; autorisation = décision humaine déclarative liée à *cette* attestation ; ADMISSION = droit d'enchaîner jusqu'au Claim, publiée par E3-J seulement (API vérifiante, jamais `_append_record`) ; Claim (E2) = acquisition exclusive ; `CONSUMPTION` = droit consommé ; `ReadIntent` = lecture possiblement commencée ; lecture = unique accès à `S_H`.
**Cohérence des artefacts épinglés** : `attachment.commitment_content_hash` = celui de l'engagement ; `ReservationTimeProof.reservation_content_hash` = `record_content_hash` du slot `RESERVATION` de cette campagne dans la chaîne relue et son `commitment_content_hash` = celui de l'engagement ; fenêtres égales entre engagement, `RESERVATION`, attachment, autorisation ; projection et préfixe de l'autorisation égaux à ceux de l'attestation ; les champs auto-déclarés de la preuve de temps (résultat, borne, nonce, liste de confiance, type) sont **recalculés** depuis la preuve brute (`R-REPLAY`).

## 23.32.9 — Nombres décimaux (décision N18) — PROPOSED

Le sérialiseur normatif d'E3-C **refuse tout flottant** (`serialize_normative_json`) : l'alternative « nombres JSON » est impossible pour les artefacts publiés par lien (engagement, etc.) ; en outre `10000` et `10000.0` donnent des hashs différents pour une même configuration (V10, enveloppe `{"initial_capital": <valeur>}` documentée). **Représentation retenue** : chaque champ numérique de l'engagement a un **type déclaré** (`int` ou `decimal`) — table : `execution_config.initial_capital`, `spread`, `slip_in`, `slip_out` = `decimal` ; `strategy_module` = texte ; `required_warmup` = `int` ; `oos_parameters` : chaque valeur garde le type du littéral de la spécification de stratégie (entier ↔ `int`, flottant ↔ `decimal`, texte ↔ texte, booléen ↔ booléen), un désaccord de type avec le fichier historique est refusé, et un booléen n'est jamais un `int` — ; un champ `int` est un entier JSON, un champ `decimal` est un objet `{"decimal": "<chaîne>"}` ; une valeur d'un autre type est refusée (`10000` entier pour un champ `decimal` est refusé, et inversement). La chaîne (comparée par `fullmatch`, chiffres ASCII `0-9` uniquement, aucun espace ni retour à la ligne) vérifie la grammaire `0|-?[1-9][0-9]*|-?(0|[1-9][0-9]*)\.[0-9]*[1-9]` (aucun `-0`, aucun exposant, aucun `+`, aucun zéro de fin) **et** le contrôle d'identité aller-retour `canon(float(s)) == s`, avec `canon(x)` : refuser `nan`/`inf` ; `t = format(Decimal(repr(x)), 'f')` ; si `t` contient un point, retirer les zéros de fin puis le point final ; refuser `t == '-0'`. Une chaîne qui n'est pas la forme la plus courte du double qu'elle désigne est **refusée** (aucun arrondi silencieux). Vecteurs V10 (échantillonneur du test de propriété : `random.Random(20261020).getrandbits(64)` interprété comme `>d`, premiers 20 000 doubles finis).
Égalité avec le moteur : `float(s)` doit être exactement la valeur du fichier historique correspondant (`config_used.json`, plan) ; sinon refus (aucune conversion silencieuse). **Limites** : `config_used_hash` et `validation_run_record_hash` (Décision 20.3) restent calculés sur le `repr` de flottants Python (non reproductibles inter-langages) et sont épinglés comme hashs opaques ; l'égalité entre coûts engagés et coûts réellement utilisés par les folds n'est pas prouvable (23.25). Anciens artefacts : inchangés (aucun n'est relu avec cette représentation).

## 23.32.10 — Compatibilité et prérequis — PROPOSED

- **E3-A, B4, B5, B6, E3-C, E3-D : inchangés** par F5/F1 (B4 : correction C-16 ci-dessous).
- **C-16** : `RegistryRecordFact.seq` exige `>= 1` (`gate_v_exposure_inventory.py:163`) alors que le registre numérote depuis 0. Correction minimale rétrocompatible : exiger `seq >= 0` (le `source_id` utilise déjà `{seq:06d}`, la même largeur que les slots d'E3-D). Elle élargit le domaine accepté : aucune identité existante ne change (aucun A0 persisté ne porte de finding de registre). Le test publié `test_gate_v_exposure_inventory.py` (cas `dict(seq=0), ValueError`) devient `dict(seq=-1), ValueError`, avec un cas `seq=0` accepté ; ne **pas** décaler de +1 dans l'adaptateur (cela figerait l'écart dans `inventory_id`).
- **B3 v4 minimal (distinct de F1)**, tranche S-5a : version `gate_v_exposure_interpreters_v4` ajoutée à `KNOWN_B3_VERSIONS` ; trois entrées de `B3_RULES_DIGESTS` (RESULTS et SPLIT_PLAN_DIR **identiques** à v3, CAMPAIGN_DIR nouveau et figé) ; à la racine du dossier de campagne : règles **informatives** (jamais exposantes) pour `prospective_commitment.json`, `s0_provenance_declaration.json`, `reservation_time_proof.json`, `holdout_snapshot_attachment.json`, `commitment_void_record.json`, `acquisition_authorization_<seq4>.json` et l'orphelin `.exposure.tmp.<32 hexadécimaux>` (le motif d'orphelin est imposé par B2 : **`TempNaming.EXPOSURE` est réutilisé**, aucune modification d'E3-C ni de B2) ; `read_intent.json`, `data_receipt.json`, `final_holdout_closing_record.json`, `validations/` et tout nom inconnu **restent inconnus** (finding `UNKNOWN_SOURCE`, bloquants). v2 et v3 restent lisibles (digests figés ; lecture historique 23.31.6). **Aucun champ ajouté à `SourceInterpretation`, aucun changement d'identité d'E3-A.** Tests publiés à amender : `tests/test_gate_v_exposure_integration.py` (égalités de `B3_SEMANTICS_VERSION` et `KNOWN_B3_VERSIONS`), `tests/test_gate_v_exposure_store.py` (égalités de version/digests). Sans B3 v4, un fichier E3-E à la racine de la campagne produit un finding `UNKNOWN_SOURCE` irrésolu et rend la classification `UNDETERMINED` **dès la `RESERVATION`**. **Limite (C-29)** : un dossier de campagne V2 réel contient aussi `manifest.json`, `validations/<run>/validation_run.json` (WF/MC/PS : fenêtre exposée non tranchée, Q-2 → `UNKNOWN_SOURCE`), `technical_failure.json` et `manifest.update.lock` ; B3 v4 minimal ne les couvre pas. Tant que Q-2 et l'interprétation de ces fichiers ne sont pas tranchées, **un dossier V2 complet reste `UNDETERMINED`** et l'admission de bout en bout n'est **pas démontrée** (BLOCKED : décision Q-2 et règles d'interprétation). Noms de tags PROPOSÉS : `campaign.commitment`, `campaign.s0_provenance`, `campaign.time_proof`, `campaign.attachment`, `campaign.void`, `campaign.authorization`.
- **Non-rétroactivité** : aucun engagement, attestation ou autorisation n'a jamais été publié.

## 23.32.11 — AMENDEMENTS EXPLICITES aux clauses existantes (si la matrice est acceptée)

| Clause | Amendement | Nature |
|---|---|---|
| 23.17 | insérer l'**étape 11 bis** (recontrôle pré-Claim, 23.32.6.4) entre 11 (ADMISSION) et 12 (Claim) | additif |
| 23.27.3 | **amendement** : la reprise revérifie les contrôles 1, 3, 4, 5, 6, 7 de 23.27.4 (hors comptabilité) et non « seuls `inventory_id`, `static_sources_digest` et la projection » ; le contrôle s'applique aussi au chemin nominal (étape 11 bis) | modification |
| 23.13 | autorisation : `acquisition_authorization.json` (fichier unique) → `acquisition_authorization_<seq4>.json` (slots) ; noms/versions des autres artefacts **inchangés** | modification de nom |
| 23.29.1 | tolérance d'un orphelin `.exposure.tmp.*` étendue à la racine du dossier de campagne | additif |
| 23.6 | `proof_type = SYNTHETIC_FIXTURE` (registre `SYNTHETIC` seulement) ; `REVOCATION_UNKNOWN` refuse en `REAL` (éléments de révocation conservés à l'ancrage ; absents ⇒ refus) ; `accuracy` RFC 3161 absente ⇒ refus | additif / précision |
| 23.8 | la nullité est aussi refusée si un Claim existe (C-17) ; liste des six causes inchangée ; `reservation_content_hash` non nul/nul distingue « publiée puis périmée » de « refusée avant publication » | précision |
| 23.10 / matrice E3-D | ratifier P9 et P13 ; distinguer « tentative neuve » et « reprise » | ratification / précision |
| 23.11 étapes 4–5 | schéma de l'attestation (32 clés) et de l'autorisation (20 clés), hash de contenu | précision |
| 23.10 étape 8 / 23.18 | `ADMITTED_STALE` étendu aux échecs de fait de 11 bis (contrôles 1, 3, 4, 5, 6, 7) ; état dérivé recalculé à chaque tentative, non persisté (un marqueur persisté serait un amendement distinct, non proposé) | modification |
| 23.4 | représentation des nombres décimaux de l'engagement (23.32.9) | précision |
| 23.31.2 / 23.31.6 | ajout de `gate_v_exposure_interpreters_v4` aux versions connues et aux `rules_digest` | additif |
| 23.26 / 23.27.7 | le témoin de tête est rattaché à E3-E | précision |
| **23.29.3, 23.10 « Crash avant le Claim »** | **NON amendés** (l'option A les aurait amendés) | — |
| 23.24 | **aucune valeur adoptée** (marge, autorité de temps, tolérance OpenTimestamps, support du témoin, plafonds…) | — |

## 23.32.12 — Limites assumées
1. L'observation F1 est une déclaration du processus d'admission (23.32.5). 2. La fenêtre dernière-lecture→`link` est irréductible ; elle n'a de conséquence que si une ré-attestation avait une sémantique de révocation, que l'ADR n'a pas définie. 3. Authenticité de l'attestant/autorisant : déclarative (une signature détachée serait une exigence nouvelle, recommandée avant `REAL`). 4. Un hash détecte l'altération qui ne recalcule pas. 5. La suppression de l'historique des chaînes avant la première attestation reste non détectable (23.29.2 limite b) ; supprimer un fichier exposant change l'`inventory_id` (limite a). 6. `config_used_hash` / `validation_run_record_hash` : reproductibilité inter-langages non garantie (23.32.9). 7. NFC et la validité des textes dépendent de la version de la base Unicode de l'interpréteur (à épingler par un test sur `unicodedata.unidata_version`). 8. La détection locale du Claim et du `ReadIntent` est BLOCKED (E3-J) ; un Claim présent dans une **copie** du dossier n'est pas détectable localement : 23.10 le couvre par l'exclusivité de la `CONSUMPTION` par `campaign_id`.
