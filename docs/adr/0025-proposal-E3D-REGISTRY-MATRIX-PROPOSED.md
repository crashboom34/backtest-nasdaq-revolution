# Matrice de contrats E3-D (registre et admissions) — NON NORMATIVE, NON ADOPTÉE

Statut : **document de conception de la slice E3-D, 2026-10-19.** Il ne modifie pas l'ADR 0025. Chaque règle porte un statut :

- **ACCEPTED** : écrite dans l'ADR 0025 (section citée) ; l'implémenter est une conformité, pas un choix.
- **PROPOSED** : choix d'implémentation ABSENT de l'ADR, nécessaire pour écrire du code ; isolé dans une constante ou un module, nommé comme tel dans le code et les tests,
  **jamais présenté comme normatif** ; une décision future peut le changer sans toucher au reste.
- **BLOCKED** : dépend d'un composant non implémenté (E3-E engagement, preuves de temps, attestation, autorisation ; E3-J orchestrateur ; configuration root ; `REAL`) ou d'une
  décision ouverte (23.24, F1, F5). **Rien n'est simulé ni publié** : le code expose seulement l'interface typée et un refus explicite.

`REAL` = DISABLED / NOT QUALIFIED. `GATE V` = NON PASSÉE. `FINAL_HOLDOUT` = NON ACCÉDÉ. Mode implémenté : `SYNTHETIC` seulement ; tout registre `REAL` est refusé.

## 1. Structure du registre

| # | Règle | Statut | Source / note |
|---|---|---|---|
| R1 | Quatre types d'enregistrement : `RESERVATION`, `ADMISSION`, `CONSUMPTION`, `REBIND` | ACCEPTED | 23.10 |
| R2 | Un fichier `admissions/admission_<seq>.json` par enregistrement, append-only, chaîné ; le motif désigne TOUS les types | ACCEPTED | 23.10 |
| R3 | Slot 0 : `prev_content_hash` = SHA-256 de la chaîne UTF-8 `"gate_v_registry_genesis:" + instance_id` | ACCEPTED | 23.10 |
| R4 | Champs communs : `admission_semantics_version`, `registry_id`, `instance_id`, `seq`, `prev_content_hash`, type, `created_at` | ACCEPTED | 23.10 |
| R5 | Types de campagne : `campaign_id`, fenêtre, `commitment_id`, `commitment_content_hash`, hash d'identité du code, `campaign_dir_locator` (HORS identité) | ACCEPTED | 23.10 |
| R6 | `RESERVATION` ajoute `static_sources_digest` ; `ADMISSION` ajoute `static_sources_digest`, hash de projection de recouvrement, `reservation_content_hash` (`reservation_seq` informatif), `attachment_id`, `attachment_content_hash`, `content_hash` de la `ReservationTimeProof`, hashs d'attestation et d'autorisation ; `CONSUMPTION` ajoute `claim_id`, `claim_content_hash`, `admission_content_hash` | ACCEPTED pour la liste (les NOMS `attestation_hash`, `authorization_hash`, `overlap_projection_hash`, `time_proof_content_hash` sont PROPOSÉS, P13) ; `attestation_observation` n'est PAS dans l'ADR : PROPOSÉ (P9, orientation F1 §0.3 non normative), conteneur opaque borné | 23.10 |
| R6b | `reservation_seq` est **informatif** : il n'est ni vérifié contre le slot de la réservation, ni dans `admission_id` ; seul `reservation_content_hash` lie l'ADMISSION à sa RESERVATION | ACCEPTED | 23.10 (revue B, constat 2) |
| R7 | `REBIND` : ni `campaign_id` ni fenêtre ; `old_binding_hash`, `new_binding_hash`, tête restaurée (`seq`, `content_hash`), justification, nouvel `instance_id` | ACCEPTED | 23.10, 23.9 |
| R8 | `record_content_hash` = SHA-256 du JSON canonique (Décision 20.3, compact) de l'enregistrement COMPLET (`seq`, `prev_content_hash`, `created_at` inclus) ; pour une `RESERVATION`, c'est `reservation_content_hash` | ACCEPTED | 23.10 |
| R9 | `admission_id` = hash sémantique SANS `seq`, `prev_content_hash`, `campaign_dir_locator`, `reservation_seq`, `created_at` ; `admission_content_hash` = hash du contenu complet | ACCEPTED (on lit `admission_content_hash` = `record_content_hash` de l'`ADMISSION` : P11) | 23.10 |
| R10 | `instance_id` : celui du slot 0 jusqu'au premier `REBIND`, puis celui du dernier `REBIND` ; celui du `REBIND` est le NOUVEAU ; la continuité repose sur `prev_content_hash` | ACCEPTED | 23.10 |
| R11 | Numérotation dense depuis 0 ; aucun slot ne disparaît ni ne change ; un slot illisible ou un trou = chaîne rompue, arrêt de tout `REAL` | ACCEPTED | 23.10, 23.18 |
| R12 | Aucune libération ni suppression en V1 : une réservation ou une admission protège la fenêtre définitivement | ACCEPTED | 23.10 |
| R13 | Un orphelin `.registry.tmp.<uuid>` est inoffensif et ignoré par le motif `admission_*.json` | ACCEPTED (forme `<uuid>` : P3) | 23.10 étape 7, 23.9 |

## 2. Invariants et unicité

| # | Règle | Statut | Source / note |
|---|---|---|---|
| I1 | Au plus UN enregistrement de chaque type `RESERVATION`, `ADMISSION`, `CONSUMPTION` par `campaign_id` ; refus `CAMPAIGN_ALREADY_REGISTERED` (`CAMPAIGN_ALREADY_CONSUMED` pour une `CONSUMPTION`) même à contenu identique | ACCEPTED | 23.10 |
| I2 | Recouvrement `a.start < b.end ∧ b.start < a.end` en instants UTC contre toute `RESERVATION` ou `ADMISSION` d'un AUTRE `campaign_id` ; une fenêtre illisible bloque tout ; granularité globale (aucune clé d'instrument) | ACCEPTED | 23.10 |
| I3 | Aucune paire recouvrante de campagnes différentes ne coexiste dans la chaîne | ACCEPTED | 23.10 (argument de sérialisation) |
| I4 | `ADMISSION` : une `RESERVATION` de la MÊME campagne, du même `commitment_content_hash` et de la même fenêtre existe et est liée par `reservation_content_hash` | ACCEPTED | 23.10 |
| I5 | `CONSUMPTION` : une `ADMISSION` de la même campagne existe et est liée par `admission_content_hash` ; aucune `CONSUMPTION` de ce `campaign_id` | ACCEPTED | 23.10 |
| I6 | États dérivés : `RESERVED`, `ADMITTED`, `CONSUMED`, `CONSUMED_UNCONFIRMED`, `INCONSISTENT` (Claim sans admission, `ADMISSION` sans `RESERVATION` correspondante, `CONSUMPTION` sans `ADMISSION`, deux enregistrements du même type, trou, contradiction) | ACCEPTED | 23.18 |
| I7 | `RESERVATION_STALE`, `ADMITTED_STALE`, `CLAIM_ONLY`, `INTENT_*`, `RECEIPT_*`, `CLOSED_*`, `EXECUTION_VOID_*` : dérivent d'artefacts HORS registre ou de l'étape 8 (non enregistrée) | **BLOCKED** (E3-J, E3-G) | 23.18 |
| I8 | Une copie du dossier de campagne conserve son `campaign_id` : elle ne peut ni réserver deux fois, ni réutiliser une admission suivie d'une `CONSUMPTION` | ACCEPTED | 23.10 |

## 3. Lecture stricte

| # | Règle | Statut | Source / note |
|---|---|---|---|
| L1 | Lire la chaîne entière, vérifier hashs et numérotation dense | ACCEPTED | 23.10 étape 1 |
| L2 | Échec fermé : aucune réparation, aucun repli, jamais « absent » pour un fichier présent invalide | ACCEPTED (principe) | 23.9, 23.18, 23.29.4 |
| L3 | Largeur du numéro de slot : 6 chiffres décimaux (`admission_000000.json`), tout autre nom refusé | PROPOSED | l'ADR dit `<seq>` sans largeur |
| L4 | Table fermée du répertoire `admissions/` : seuls `admission_<seq6>.json` et les orphelins `.registry.tmp.<uuid>` ; tout autre nom est REFUSÉ | PROPOSED | cohérent avec B2/B3 ; l'ADR dit seulement « ignoré par le motif » |
| L5 | Octets persistés = JSON normatif d'E3-C (`serialize_normative_json`, point fixe d'octets vérifié) ; le hash porte sur le JSON canonique compact, pas sur les octets | PROPOSED | 23.29.4 ne couvre pas le registre (revue G-M7) |
| L6 | Plafonds de lecture provisoires : taille d'un slot, profondeur JSON, nombre de slots | PROPOSED | aucune valeur n'est dans l'ADR (23.24 « limite mémoire du chargeur ») |
| L7 | JSON strict : pas de BOM, clé dupliquée, constante non finie, flottant ; version connue exacte | ACCEPTED (esprit 23.29.4) / PROPOSED (application au registre) | |
| L8 | `identity.json` : `registry_id`, `instance_id`, `mode`, profil de durabilité ; `REAL` exige `POSIX_DIR_FSYNC` ; `SYNTHETIC` utilise `SIMULATED_DURABLE` | ACCEPTED (champs) | 23.9, 23.2 |
| L9 | Registre `REAL` : REFUSÉ. Le refus est structurel (`mode == REAL` ⇒ `MODE_REFUSED` à la lecture) ; il n'existe pas de constante nommée `REAL_FINAL_HOLDOUT_ENABLED` dans ce lot | ACCEPTED (REAL désactivé, 23.2) ; réalisation PROPOSÉE | 23.2 |
| L10 | Liaison physique (UUID du volume, inode, identifiant machine, hôte autorisé, système de fichiers, permissions, UID du compte de service) | **BLOCKED** (configuration root, `REAL`) | 23.9, 23.24 |

## 4. Publication (étapes de 23.10)

| # | Règle | Statut | Source / note |
|---|---|---|---|
| W1 | Étapes 3 à 7 : enregistrement du slot `n+1`, temporaire dans le MÊME répertoire, `link`, `fsync`, suppression du temporaire, via la primitive E3-C | ACCEPTED | 23.10, 23.22 |
| W2 | `FileExistsError` = slot occupé : on revient à l'étape 1 et on REVÉRIFIE tout ; jamais publier directement dans le slot suivant sans revérifier | ACCEPTED | 23.10 étape 5, 23.27.4 |
| W3 | Nombre de tentatives borné par appel ; au-delà : `REGISTRY_CONTENTION`, rien n'est publié ; AUCUNE valeur par défaut | ACCEPTED (borne) / valeur BLOCKED (23.24) : l'appelant la fournit explicitement | 23.10, 23.24 |
| W4 | Un second enregistrement du même type et de la même campagne n'est JAMAIS publié, même à contenu identique | ACCEPTED | 23.10 |
| W5 | `RESERVATION` et `ADMISSION` : relecture et réutilisation SANS publication si le contenu sémantique est identique ; jamais une publication ; re-confirmation par `fsync` du répertoire permise | ACCEPTED | 23.10 |
| W5b | Une `ADMISSION` n'est réutilisable que si **aucune `CONSUMPTION` n'existe dans le registre pour ce `campaign_id`** : sinon refus `CAMPAIGN_ALREADY_CONSUMED`, avant toute re-confirmation | ACCEPTED (23.10 « Même campaign_id, deux tentatives » ; défaut trouvé par la revue B, corrigé) | 23.10 |
| W5c | Condition « aucun Claim ni `ReadIntent` n'existe localement » de la réutilisation d'une admission : artefacts HORS registre | **BLOCKED** (E3-J) ; documenté dans la docstring de `find_reusable_record`, jamais simulé | 23.10 |
| W5d | Identité sémantique d'une `RESERVATION` réutilisable (l'ADR dit « contenu sémantique identique » sans la définir) : même règle que `admission_id` | PROPOSED (P19) | |
| W15 | Écrivain d'un slot dense et irréparable : prouver AVANT la publication que le lecteur strict relira exactement ces octets (taille ≤ plafond de lecture, nombre de slots ≤ plafond, aller-retour octets → JSON strict → mêmes octets) ; sinon rien n'est publié | ACCEPTED comme précondition d'E3-C (AI_HANDOFF §61, `atomic_json_store.py` § préconditions) ; valeurs des plafonds PROPOSÉES (P8) | revue A, constat HIGH-1 |
| W6 | `CONSUMPTION` : AUCUNE réutilisation, AUCUNE idempotence ; refusée dans tous les cas où une `CONSUMPTION` de ce `campaign_id` existe ; re-confirmation permise seulement DANS l'appel qui l'a publiée | ACCEPTED | 23.10, 23.18 |
| W7 | `CONSUMPTION` : `claim_content_hash` égal à celui du Claim relu par E2 | ACCEPTED ; implémenté par RELECTURE du Claim par `load_final_holdout_access_claim` (jamais un booléen ni un objet fourni) | 23.10 |
| W8 | Un slot visible non confirmé reste binding ; `PublishedUnconfirmed` : étape suivante interdite ; ni republication ni suppression | ACCEPTED | 23.10, E3-C |
| W9 | `RESERVATION` : engagement valide ; `static_sources_digest` recalculé et ensemble pertinent vide ; aucune attestation | **BLOCKED** (E3-E engagement ; E3-B/E3-J recalcul) | 23.10 |
| W10 | `ADMISSION` : `ReservationTimeProof` valide et `borne + marge ≤ ws` ; préfixe de chaîne épinglé présent ; projection et `static_sources_digest` identiques à ceux de l'attestation ; attestation valide ; autorisation valide ; déclarations inchangées ; sept contrôles (23.27.4) répétés après tout conflit | **BLOCKED** (E3-E, E3-J) | 23.10, 23.27.4 |
| W11 | `REBIND` : cérémonie humaine ; tête restaurée vérifiée contre les témoins de tête | **BLOCKED** (témoins de tête, configuration root) | 23.9, 23.10 |
| W12 | Témoin de tête (6 bis) : preuve de temps et copie hors hôte après chaque enregistrement | **BLOCKED** (E3-E, support 23.24) | 23.6, 23.10 |
| W13 | Étape 8 : revérifier `static_sources_digest` après publication (`RESERVATION_STALE`, `ADMITTED_STALE`) | **BLOCKED** (E3-J) | 23.10 |
| W14 | Aucune publication de `RESERVATION`, `ADMISSION` ni `REBIND` n'est exposée publiquement : un moteur d'ajout INTERNE (`_append_record`) les exerce (concurrence, recouvrement) ; il exige `unproven_synthetic=True` (reconnaissance explicite qu'AUCUNE preuve n'est vérifiée) ; un booléen n'est jamais une preuve | PROPOSED (garde de conception) | mission E3-D, revue B constat 4 |

## 5. Interfaces préparées (F1 / F5, sans les figer)

| # | Règle | Statut |
|---|---|---|
| F1 | Vue d'`ADMISSION` AUTORITATIVE en lecture seule : l'enregistrement `ADMISSION` d'une chaîne VÉRIFIÉE, jamais un témoin fourni par l'appelant | PROPOSED (orientations 0 de la proposition F1/F5) |
| F2 | L'ADMISSION épingle l'attestation et l'autorisation par `attestation_hash` et `authorization_hash` (SHA-256 hexadécimal, jamais interprétés : ADR 23.10 « hashs d'attestation et d'autorisation » ; ce que le hash d'attestation COUVRE reste BLOCKED, F5 / E3-E). `attestation_observation` (plus haut slot d'attestation observé à l'ADMISSION) est un conteneur OPAQUE borné (profondeur, taille), couvert par la chaîne de hashs, jamais interprété | hashs : ACCEPTED (champs) / PROPOSED (noms) ; `attestation_observation` : PROPOSED (P9) ; la VUE F1 (exposition, recouvrement) reste BLOCKED (E3-J) |
| F4 | `read_authoritative_admission(registry_root, campaign_id)` : lecture seule d'une chaîne ENTIÈRE vérifiée, barrière APRÈS la lecture, re-confirmation du slot ; ne prend aucun enregistrement ni preuve de l'appelant ; `is_probative_admission_proof` est constamment faux (registre SYNTHETIC) | PROPOSED (interface préparée, pas la vue F1) |
| F3 | Plus haut slot d'attestation observé « au moment de l'ADMISSION » : champ opaque ; sa VÉRIFICATION (atomicité) est celle d'E3-J | PROPOSED / BLOCKED (E3-J) |

## 6. Choix PROPOSÉS (liste de décision)

P1 largeur du slot (6 chiffres) · P2 octets = JSON normatif d'E3-C · P3 forme de l'orphelin `.registry.tmp.<uuid4 canonique>` (déjà dans E3-C) · P4 formats de `registry_id` (identifiant ASCII `[A-Za-z0-9_.-]{1,128}`) et d'`instance_id` (32 hexadécimaux) ·
P5 `created_at` au format normalisé UTC d'E3-A (`normalize_utc_instant`) · P6 valeur de `admission_semantics_version` (`gate_v_registry_record_v1`) · P7 table fermée de `admissions/` · P8 plafonds de lecture provisoires ·
P9 conteneur opaque borné `attestation_observation` (orientation F1 §0.3) · P10 argument `max_attempts` obligatoire sans défaut · P11 `admission_content_hash` = `record_content_hash` de l'`ADMISSION` ·
P12 `campaign_dir_locator` : texte non vide hors identité · P13 noms des champs de hash (`static_sources_digest`, `overlap_projection_hash`, `code_identity_hash`, `attestation_hash`, `authorization_hash`, `time_proof_content_hash`) · P14 initialisation `SYNTHETIC` d'un registre (`identity.json` + `admissions/`) ; `identity.json.instance_id` est l'instance de GENÈSE (slot 0), l'instance en vigueur se lit dans la chaîne : une restauration REAL qui voudrait un `identity.json` à l'instance courante est la cérémonie `REBIND` (W11, BLOQUÉE) ·
P15 `OVERLAPPING_REGISTRATION` (nom déjà défini par E3-A, `AdmissionRefusal`) ·
P16 un `REBIND` change au moins une liaison (`old_binding_hash` ≠ `new_binding_hash`) · P17 la tête restaurée d'un `REBIND` est le slot qui le précède · P18 une `CONSUMPTION` répète fenêtre et `commitment_content_hash` de son `ADMISSION` ·
P19 identité sémantique d'une `RESERVATION` (comme `admission_id`) · P20 `LISTING_ATTEMPTS = 3` re-listages de `admissions/` avant de conclure à un trou (un listage peut être déchiré par un ajout concurrent) ·
P21 codes de refus au-delà des trois de l'ADR (`CHAIN_LINK_BROKEN`, `REGISTRY_MISMATCH`, `INSTANCE_MISMATCH`, `PREDECESSOR_MISSING`, `PREDECESSOR_MISMATCH`, `REBIND_INVALID`, `INVALID_RECORD`) · P22 un `REBIND` ne revient jamais à un `instance_id` déjà porté par la chaîne ·
P23 ordre des contrôles (lien de chaîne, instance, unicité, recouvrement, liens entre types) : l'ADR liste les contrôles sans fixer d'ordre · P24 plafonds `MAX_RECORD_BYTES = 65536`, `MAX_OPAQUE_BYTES = 16384`, `MAX_OPAQUE_DEPTH = 8`, `MAX_SLOT_BYTES = 262144`, `MAX_SLOTS = 100000`, `MAX_IDENTITY_BYTES = 4096` ·
P25 garde `unproven_synthetic=True` du moteur interne.

## 6 bis. Limites assumées (résiduelles, non corrigées)

- `created_at` est fourni par l'appelant et n'est contraint ni en ordre ni en monotonie (l'ADR n'en exige pas ; il garde les hashs déterministes).
- Un trou ou une altération de la QUEUE de la chaîne n'est indétectable sans témoin de tête (W12, BLOQUÉ).
- `publish_consumption` reçoit un `plan` en mémoire ; E2 vérifie sa structure et la liaison du Claim, pas qu'il est le `plan.json` persisté (frontière de confiance E2 22.5).
- Entrées d'annuaire parasites et orphelins `.registry.tmp.*` ne sont pas bornés en nombre (la mémoire de lecture est bornée par slot, pas par nombre d'orphelins).
- `AuthoritativeAdmission` est constructible par n'importe qui : sa nature non probante tient à `is_probative_admission_proof` (constamment faux) et au mode SYNTHETIC, pas à une capacité.
- Le mode SYNTHETIC / REAL n'est lié ni à la chaîne ni à la genèse : la liaison physique relève de la configuration root hors registre (23.9, BLOQUÉ).

## 7. Dépendances

E3-C (publié) : `publish_json_by_link`, `confirm_published_slot`, `directory_read_barrier`, `serialize_normative_json`. E3-A : `normalize_utc_instant`, `OwnRecordStage`, `AdmissionRefusal`. E2 (publié) : `load_final_holdout_access_claim`.
**E3-E** : engagement, `ReservationTimeProof`, attestation (jeu de clés, hash F5), autorisation, témoin de tête. **E3-J** : orchestration, sept contrôles, étape 8, dérivation de l'étage, vue F1.
**Racine / REAL** : liaison physique, permissions, système de fichiers qualifié, volume, coupure d'alimentation.
