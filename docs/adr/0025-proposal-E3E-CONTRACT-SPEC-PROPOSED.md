# Spécification E3-E (engagement, preuves de temps, attestation, autorisation, attachment, nullité, témoin de tête) — NON NORMATIVE, NON ADOPTÉE

**Statut : SPÉCIFICATION PROPOSÉE (2026-10-20), révision 6 (corrigée après six revues indépendantes : `…-REVIEWS.md`), mission « E3-E design gate ». Aucun code de production E3-E n'existe ni n'est autorisé avant acceptation des décisions normatives
de `docs/adr/0025-proposal-E3E-DECISIONS-PENDING.md`.** Le texte d'autorité reste `docs/adr/0025-gate-v-validation-policy-v1.md` (addenda 23.27–23.31). Compagnons :
`docs/adr/0025-proposal-E3E-23.32-ATTESTATION-F1-F5-PROPOSED.md` (F1/F5 ; **23.32.x** y est cité), `docs/adr/0025-proposal-E3E-TDD-PLAN-AND-RED-MATRIX-PROPOSED.md`,
`docs/adr/0025-proposal-E3E-HASH-VECTORS.json`, `docs/adr/0025-proposal-E3E-REVIEWS.md`.
`REAL` = DISABLED / NOT QUALIFIED · `GATE V` = NON PASSÉE · `FINAL_HOLDOUT` = NON ACCÉDÉ · `F1` = SPEC BLOCKED · `F5` = PROPOSED · `E3-J` = non implémenté · `E3-F` (ingesteur) = non implémenté.
Étiquettes : **ACCEPTED** (écrit dans l'ADR, section citée) · **PROPOSED** (ce document) · **BLOCKED** (décision ou composant absent) · **IMPLEMENTED** (code publié).

---

## 1. Périmètre et re-découpage proposé (N15)

Le périmètre « E3-E » est réparti sur **deux textes de l'ADR** : 23.26 (engagement, preuves de temps, attachment, nullité) et 23.27.7 (engagement, preuves de temps, **modèles d'attestation et d'autorisation**). Seul le **témoin de tête** (23.6, 23.10 6 bis) n'est placé dans aucune tranche (C-1, corrigé : la révision 1 prétendait à tort que l'attestation et l'autorisation n'étaient placées nulle part).
Proposition de sous-tranches (chacune RED → GREEN → revue, suite existante verte) :

| Tranche | Contenu | Dépend de | Statut |
|---|---|---|---|
| E3-E0a (= S-5a) | **B3 v4 minimal** : règles informatives pour les noms E3-E à la racine de la campagne, `rules_digest` v4, lecture historique v2/v3, inconnus toujours bloquants ; **aucun champ ajouté à `SourceInterpretation`** ; amende les tests publiés listés (23.32.10) | décision N8 | PROPOSED |
| E3-E0c | **Correction d'un module publié** : `RegistryRecordFact.seq >= 1` vs numérotation du registre depuis 0 (C-16) | décision utilisateur (module B4 publié) | PROPOSED (défaut latent, hors E3-E) |
| E3-E1 | Attestation : modèle pur, hash F5, vecteurs, relecture stricte | N1, N2, N16 | PROPOSED (BLOCKED par N1/N2) |
| E3-E2a | Vérification d'attestation, volet **interne** : relecture, A0, déclarations, lignée, préfixe, classification (sans engagement/attachment/preuve de temps) | E3-E1 | PROPOSED |
| E3-E2b | Vérification d'attestation, volet **liaisons** : engagement, attachment, preuve de temps, faits de chronologie (23.32.4 bis) | E3-E2a, E3-E5, E3-E6, E3-E7 | PROPOSED |
| E3-E3 | Observation F1, `history_digest`, recontrôle pré-Claim (11 bis), tableau des slots postérieurs, fonction de neutralisation | N3–N7, N19 | **SPEC BLOCKED** |
| E3-E4 | Autorisation : modèle, hash, relecture, liens | N10 | PROPOSED |
| E3-E5 | Engagement : modèle, ids, relecture, liaison au plan et à la pré-enregistration | N18 | PROPOSED (BLOCKED par N18) |
| E3-E6 | `ReservationTimeProof` : modèle, machine d'états de vérification, faits `TimeProofFact` ; vérificateurs RFC 3161 / OpenTimestamps réels | N11–N13, 23.24 | modèle PROPOSED ; vérificateurs **BLOCKED** |
| E3-E7 | Attachment (dérivation depuis un `IngestionRecord`) et `CommitmentVoidRecord` | N14, N17, E3-F | PROPOSED ; chemin réel **BLOCKED** (E3-F) |
| E3-E8 | Témoin de tête : modèle et détection de retour en arrière | 23.24 (support) | modèle PROPOSED ; émission **BLOCKED** |
| E3-E9 | Rapport de prérequis d'`ADMISSION` en lecture seule (compose E3-E1…E3-E8 et les vues d'E3-D) | E3-E2…E3-E8 | PROPOSED |

**E3-E ne publie jamais de `RESERVATION`, d'`ADMISSION`, de `REBIND` ni de `CONSUMPTION`** et n'appelle jamais E2. Ces publications relèvent d'une API de publication vérifiante d'E3-J (ou d'un module E3-D v2 appelé par E3-J) qui **relit** les artefacts via les fonctions d'E3-E.

## 2. Principes d'ingénierie (applicables à toutes les tranches)

- `R-REREAD` : chaque vérificateur relit le disque ; aucun objet vérifié n'est passé par valeur à un publieur (E3-D : `AuthoritativeAdmission` est constructible par n'importe qui).
- `R-REPLAY` : tous les champs auto-déclarés d'une `ReservationTimeProof` (« résultat de la vérification », `time_bound_utc`, `nonce_hex`, `trust_list_sha256`, `proof_type`) sont des **auto-déclarations** ; leur hash en prouve l'intégrité, pas l'exactitude. La borne, le nonce et l'empreinte de la liste de confiance sont **recalculés** depuis la preuve brute et la liste commitée à l'ancrage ET à l'`ADMISSION` ; la condition `borne + marge ≤ ws` utilise la borne **recalculée**, jamais la valeur stockée.
  Honnêteté sur la seconde vérification (hors ligne) : elle rejoue les éléments de révocation **conservés** à l'ancrage ; elle ne détecte donc pas une compromission **ultérieure** de l'autorité de temps ; sa valeur est de détecter une altération locale de la preuve conservée. Le nonce n'a de sens que dans l'échange en ligne.
- `R-ONEBUFFER` / `R-STRICTREAD` : un seul tampon par vérification (les octets vérifiés sont ceux qu'on hache) ; toute lecture de fichier reprend `read_strict_file` de B5 (`lstat`, ouverture sans suivre de lien, régularité, taille bornée avant lecture, stabilité) ; plafonds de taille provisoires non normatifs par artefact et pour `evidence_b64` (23.24).
- `R-PRECLAIM` : recontrôle pré-Claim (étape 11 bis de 23.17, 23.32.6.4, N4 option C) — avant tout appel d'E2 — et seulement si aucun Claim ni ReadIntent local n'existe (E3-J) —, E3-J relit l'ADMISSION autoritative et refait les contrôles 1, 3, 4, 5, 6, 7 de 23.27.4 sur les artefacts **épinglés**, plus le slot épinglé, `history_digest` et la durabilité des artefacts épinglés. La garde bloquante « PCG » de la révision 3 est abandonnée.
- `R-NOBOOL` : aucune API ne retourne un booléen « ok » ni un objet « vérifié » transmissible ; les vérificateurs lèvent un refus typé ou retournent un rapport **descriptif** (liste de faits et d'écarts) que le publieur ne peut pas substituer à une relecture.
- `R-RECOVERY` (révision 5) : la reprise **continue** l'ADMISSION existante (`read_authoritative_admission` : barrière, reconfirmation, `campaign_state == ADMITTED`, **et aucun Claim ni ReadIntent local** : E3-J, BLOCKED — le registre ne voit pas le Claim) puis l'étape 11 bis sur les artefacts épinglés ; elle **ne reconstruit aucun candidat** à partir de l'état courant du disque (un candidat porterait l'attestation « la plus haute » et ne pourrait pas égaler `admission_id`). `find_reusable_record` ne sert qu'à rejouer une *publication* dans la même tentative. Détail : 23.32.6.5 et N7.
- `R-NOCALLBACK` : aucun paramètre `bool`/callback/`Callable` n'est une preuve ; les tests `TypeError` d'E3-D sont la référence.
- `R-FAILCLOSED` : un refus typé à chaque anomalie, pas de repli, pas de réparation, pas de suppression.
- `R-SYNTHETIC` : toute fonction qui dépend du mode lit le mode du registre ; `REAL` est refusé.
- `R-SINGLE-CANON` : chaque module duplique `_canonical_json` (convention du dépôt : helpers privés non importés entre modules) ; un test inter-modules prouve des octets identiques sur les vecteurs.

## 3. Échelle des garanties (ne jamais confondre)

| Niveau | Ce qu'il établit | Moyen | Où dans E3-E |
|---|---|---|---|
| G1 Intégrité | le contenu n'a pas changé depuis le calcul du hash | SHA-256 de contenu, point fixe d'octets | tous les artefacts |
| G2 Liaison | un artefact désigne exactement un autre (par hash) | épinglages, égalités de hash relus sur disque | attestation, autorisation, attachment, ADMISSION |
| G3 Ordre | un enregistrement précède un autre dans la chaîne | numérotation dense, `prev_content_hash` (E3-D) | registre |
| G4 Temps | l'empreinte existait avant une borne | RFC 3161 ou OpenTimestamps **confirmé**, vérifié | `ReservationTimeProof`, témoin de tête (BLOCKED : autorité non choisie) |
| G5 Authenticité | qui a écrit | **aucune** en V1 (identité déclarative) ; signature détachée = exigence nouvelle (N10) | — |
| G6 Autorisation | qu'un humain a décidé | autorisation nominative **déclarative** liée par hash | autorisation (G5 absent) |

Tout hash est G1 (+ G2 si épinglé) ; **aucun hash n'est G4, G5 ou G6**. `created_at`, `attested_at`, dates de fichier, SHA Git et horloge système ne sont jamais G4 (23.6).

## 4. Matrice de statuts — les neuf composants demandés

| # | Composant | Spécifié par l'ADR | Schéma exact | Code | Statut global |
|---|---|---|---|---|---|
| 1 | `GateVProspectiveCommitment` | ACCEPTED 23.4 (chemin, version, liste de champs, deux hashs) | PROPOSED (§5.1) | aucun | **PROPOSED** ; N18 ouvert (flottants) |
| 2 | `ReservationTimeProof` | ACCEPTED 23.6 (champs, deux vérifications, fail-closed) | PROPOSED (§5.2) | `TimeProofFact`/`TimeProofStatus` d'E3-A (consommateur) | modèle **PROPOSED** ; vérificateurs **BLOCKED** |
| 3 | Attestation d'exposition | ACCEPTED 23.11/23.27.3/23.29.3 (chemin, épinglages minimaux, « n'autorise rien ») ; 23.27.7 la place dans E3-E | PROPOSED (23.32.1, 32 clés) | lecture d'octets seulement (B6) | **PROPOSED** (F5) ; F1 **SPEC BLOCKED** |
| 4 | Autorisation humaine d'acquisition | ACCEPTED 23.11 étape 5 (liens) | PROPOSED (23.32.8, §5.4) | aucun | **PROPOSED** |
| 5 | `HoldoutSnapshotAttachment` | ACCEPTED 23.8 (chemin, `attachment_id`, hash) | PROPOSED (§5.5) | aucun | **PROPOSED** ; chemin réel **BLOCKED** (E3-F) |
| 6 | `CommitmentVoidRecord` | ACCEPTED 23.8 (six causes, exclusif, nominatif, refusé après CONSUMPTION/ReadIntent) | PROPOSED (§5.6) | aucun | **PROPOSED** ; N14 ouvert |
| 7 | Témoin de tête | ACCEPTED 23.6, 23.9, 23.10 6 bis (rôle, calendrier) | PROPOSED (§5.7) | aucun | modèle **PROPOSED** ; émission **BLOCKED** (support 23.24) |
| 8 | Interfaces avec E3-D | ACCEPTED (champs de l'ADMISSION) | PROPOSED (23.32.5, §6) | **IMPLEMENTED** : `read_authoritative_admission`, `find_reusable_record`, `publish_consumption`, `read_registry`, `assemble_record` | usage **PROPOSED** ; E3-D inchangé |
| 9 | Interfaces futures avec E3-J | ACCEPTED (23.17 séquence, 23.27.4 sept contrôles) | PROPOSED (§6) | aucun | **BLOCKED** (E3-J non spécifié ici) |

## 5. Fiches d'artefacts

Colonnes communes à chaque fiche : identité, schéma, hash sémantique, hash de contenu, préimage, références, publication, relecture, crash, refus, autorité, garanties. Recette de hash de contenu commune (PROPOSED sauf commitment/attachment : ACCEPTED) :
`SHA-256(UTF-8(canonical_json(record privé de sa seule clé de hash)))`, `canonical_json` = Décision 20.3. Représentation persistée = sérialiseur normatif de 23.29.4 (point fixe d'octets). Textes NFC ; instants UTC normalisés ; aucun flottant (sauf N18).

### 5.1 `GateVProspectiveCommitment`
| Attribut | Contenu |
|---|---|
| Identité / version | `gate_v_prospective_commitment_v1` (ACCEPTED) ; chemin `<campaign_dir>/prospective_commitment.json`, **un seul par campagne**, création exclusive durable (ACCEPTED) |
| Schéma (clés PROPOSÉES, liste ACCEPTED) | `version`, `campaign_id`, `preregistration_id`, `preregistration_content_hash`, `campaign_protocol_fingerprint`, `window_start_utc`, `window_end_utc` (égales à `plan.final_holdout`), `research_snapshot_id` (S0), `s0_provenance_declaration_hash`, `oos_parameters` (littéraux), `oos_parameter_selection_rule` = `LITERAL_PREDECLARED`, `execution_config` {`initial_capital`, `spread`, `slip_in`, `slip_out` = `decimal` ; `strategy_module` = texte} (types : 23.32.9 ; `oos_parameters` typés par le littéral de la spécification de stratégie), `execution_config_hash`, `code_identity` {SHA Git complet, arbre propre, hashs SHA-256 des fichiers du moteur / stratégie / `validation_oos.py` / chargeur / orchestrateur / ingesteur / registre, `ENGINE_VERSION`, `required_warmup`}, `code_identity_hash` (= hash canonique de `code_identity`, PROPOSED), `validation_run_refs` (WF, MC, PS : id + `validation_run_record_hash`), `config_used_hash`, `acquisition_rule` {fournisseur, symbole, convention de cotation, timeframe, fuseau, calendrier et sessions, règle de couverture, adaptateur et version, tentatives maximales d'ingestion, plage `(fin de S0, we)`}, `registry_id`, `t_sel_utc`, `commitment_id`, `created_at`, `commitment_content_hash` |
| Hash sémantique | `commitment_id` = SHA-256(canonical(**champs sémantiques**)) = tous les champs **sauf** `commitment_id`, `created_at`, `commitment_content_hash` (ACCEPTED) |
| Hash de contenu | `commitment_content_hash` = SHA-256(canonical(champs sémantiques + `commitment_id` + `created_at`)) = tous les champs sauf `commitment_content_hash` (ACCEPTED). **Écart voulu avec E1** (`created_at` y est exclu des deux hashs) ; ce n'est pas une preuve de date |
| Références | plan V2, pré-enregistration, `ValidationRun` WF/MC/PS, `S0ProvenanceDeclaration`, dépôt Git (SHA complet courant = SHA engagé, à chaque démarrage `REAL`) |
| Séquence de publication | créé après D5 complète (`EVIDENCE_COMPLETE_AWAITING_FINAL_HOLDOUT`) et avant `ws` → `RESERVATION` durable → `ReservationTimeProof` (ACCEPTED 23.4). Primitive de lien d'E3-C (singleton : N9) |
| Relecture stricte | octets stricts + point fixe ; clés exactes ; deux hashs recalculés ; fenêtre = `plan.final_holdout` ; `campaign_id` = plan ; liaison pré-enregistration (id ET `content_hash` relus) ; `S0` relu ; SHA Git courant = engagé ; ensemble des `validation_run_record_hash` relus ; **aucune** donnée de marché lue |
| Crash | fichier tronqué au nom attendu = engagement inutilisable (singleton non réparable) → d'où N9 (publication complète-ou-absente) ; orphelin temporaire inoffensif ; un engagement sans `RESERVATION` ne protège aucune fenêtre (23.8) |
| Refus | `COMMITMENT_INVALID`, `…_VERSION_UNKNOWN`, `…_HASH_MISMATCH`, `…_WINDOW_MISMATCH`, `…_PREREGISTRATION_MISMATCH`, `…_CODE_IDENTITY_MISMATCH`, `…_DUPLICATE` (noms PROPOSÉS) |
| Autorité de vérification | E3-E (structure, hashs, liaisons) ; la **validité scientifique du protocole** relève du Human Gate, pas d'E3-E |
| Garanties démontrables | G1 (altération détectable), G2 (liaisons) ; **pas** G4 (la date de l'engagement n'est pas prouvée par lui), **pas** G5 |
| Ouvert → proposition | **N18** : champs numériques typés (`int` ou `{"decimal": …}`), grammaire stricte sans `-0`, identité aller-retour ; le sérialiseur d'E3-C refuse les flottants ; limite sur les hashs hérités (23.32.9) |

### 5.2 `ReservationTimeProof`
| Attribut | Contenu |
|---|---|
| Identité / version | `gate_v_reservation_time_proof_v1` (nom **ACCEPTED**, 23.13) ; chemin `<campaign_dir>/reservation_time_proof.json`, **un seul par engagement**, création exclusive durable, écrit **seulement pour une preuve vérifiée** (ACCEPTED 23.6) |
| Schéma (liste ACCEPTED, clés PROPOSÉES) | `version`, `proof_type` ∈ {`RFC3161`, `OPENTIMESTAMPS`} (+ `SYNTHETIC_FIXTURE`, N11, `SYNTHETIC` seulement), `campaign_id`, `reservation_content_hash`, `commitment_content_hash`, `evidence_b64` + `evidence_sha256` (octets de la preuve ; chaîne de certificats ou en-têtes inclus ; plafond provisoire), `verifier_tool_id`, `verifier_tool_version`, `trust_list_sha256`, `time_bound_utc` (= `genTime + exactitude`), `nonce_hex` (RFC 3161), `verification_result` ; **tous ces champs sauf `evidence_*` sont auto-déclarés et recalculés** (`R-REPLAY`) ; `created_at`, `time_proof_content_hash` |
| Hash sémantique | non défini par l'ADR ; **aucun `_id` séparé** (PROPOSED) |
| Hash de contenu | `time_proof_content_hash` = recette commune ; c'est lui que l'`ADMISSION` (`time_proof_content_hash`) et le `ReadIntent` épinglent (ACCEPTED 23.6/23.10) |
| Préimage de la preuve elle-même | RFC 3161 : `messageImprint` = les **32 octets** du `reservation_content_hash` décodé, algorithme SHA-256 (ACCEPTED 23.6) — ni son texte hexadécimal, ni le hash de ce texte (contre-vecteur V8). OpenTimestamps : même empreinte de 32 octets |
| Références | `RESERVATION` (par `record_content_hash` dans la chaîne relue), engagement, liste de confiance **commitée dans le dépôt** à l'empreinte épinglée par l'engagement |
| Vérification (deux fois : à l'ancrage en ligne, à l'`ADMISSION` et au démarrage d'E3 hors ligne — ACCEPTED 23.6) | (1) empreinte = `reservation_content_hash` de **sa propre** réservation ; (2) RFC 3161 : signature, chaîne vers une autorité de la liste de confiance, politique, validité du certificat **à `genTime`**, `nonce`, exactitude, révocation ; OpenTimestamps : seule une attestation de bloc **confirmée** compte ; (3) `borne + marge ≤ ws` ; marge ≤ 0 ou absente = non vérifié (E3-A F4). **La marge, l'autorité de temps et l'outil de vérification ne sont PAS choisis ici** (23.24) |
| Machine d'états (sortie = `TimeProofFact` d'E3-A) | `VALID` (borne + cible), `INVALID` (empreinte différente, signature fausse, nonce faux), `UNVERIFIABLE` (outil indisponible, chaîne absente, autorité hors liste, `genTime` illisible/postérieur, preuve en attente, révocation inconnue — N12), `ABSENT`. Toute autre issue = pas de `VALID`. `TimeProofStatus` d'E3-A reste inchangé |
| Crash | un échec ne laisse aucun artefact (engagement non ancré) ; la preuve est rejouable après `RESERVATION` durable ; sans preuve valide la réservation reste et la campagne est inutilisable (23.18) |
| Refus | `TIME_PROOF_UNVERIFIABLE` (ACCEPTED, 23.6), `TIME_PROOF_NOT_OWN_RESERVATION`, `TIME_PROOF_ANCHORED_TOO_LATE`, `TIME_PROOF_MARGIN_MISSING`, `TIME_PROOF_HASH_MISMATCH` (PROPOSÉS) |
| Autorité | un vérificateur RFC 3161/OTS **non choisi** → BLOCKED. En `SYNTHETIC`, `SYNTHETIC_FIXTURE` (octets fixtures, `probative = faux` dans le rapport) permet de tester les chemins sans prétendre à G4 |
| Garanties | G4 **uniquement** après qualification d'une autorité et d'un outil (23.21) ; jamais par un hash |

### 5.3 Attestation d'exposition — voir 23.32.1 à 23.32.6 (schéma à 32 clés, hash F5, observation, F1).

### 5.4 Autorisation humaine d'acquisition — voir 23.32.8
| Attribut | Contenu |
|---|---|
| Identité / version | `gate_v_acquisition_authorization_v1` (nom **ACCEPTED**, 23.13) ; chemin ADR : fichier **unique** `acquisition_authorization.json` ; PROPOSITION (N10) : `acquisition_authorization_<seq4>.json` (slots denses à la racine, jamais écrasés ni supprimés, **seule l'autorisation épinglée par l'`ADMISSION` compte**, les autres sont de l'historique sans effet) ; publication par la primitive de lien d'E3-C avec `TempNaming.EXPOSURE` existant (N9) ; règles complètes (ré-autorisation, candidat, révocation, péremption) : 23.32.8 |
| Hash / préimage | `authorization_content_hash`, recette commune ; vecteur V6 |
| Références | attestation (par `attestation_content_hash`), engagement, `claim_id` (calculable depuis le plan), fenêtre, mode, `code_identity_hash`, `qualification_report_hash` (`null` seulement en `SYNTHETIC`), projection, préfixe du registre |
| Relecture / refus | comme l'attestation (jeu de clés exact, hash, point fixe, `campaign_id`) + `AUTHORIZATION_ATTESTATION_MISMATCH`, `AUTHORIZATION_CLAIM_MISMATCH`, `AUTHORIZATION_MODE_MISMATCH`, `AUTHORIZATION_STALE_PREFIX` (PROPOSÉS) |
| Garanties | G1, G2 ; **pas** G5/G6 forts : l'autorisant est déclaratif. Une autorisation ne vaut que pour **l'attestation qu'elle nomme** |

### 5.5 `HoldoutSnapshotAttachment`
| Attribut | Contenu |
|---|---|
| Identité / version | `attachment_semantics_version` = `gate_v_holdout_attachment_v1` (valeur **ACCEPTED**, 23.13 ; la révision 1 l'avait renommée à tort en `…_snapshot_attachment_v1` ; la clé `attachment_semantics_version` diffère de `version` des autres artefacts par fidélité à la préimage d'`attachment_id` de 23.8) ; `<campaign_dir>/holdout_snapshot_attachment.json`, un seul par engagement, **dérivé** de l'`IngestionRecord`, jamais choisi (ACCEPTED) |
| Schéma | `attachment_semantics_version`, `campaign_id`, `commitment_id`, `commitment_content_hash`, `research_snapshot_id`, `holdout_snapshot_id`, `ingestion_record_content_hash`, `window_start_utc`, `window_end_utc`, `attachment_id`, `created_at`, `attachment_content_hash` (liste ACCEPTED ; clés PROPOSÉES) |
| Hash sémantique | `attachment_id` = SHA-256(canonical({`attachment_semantics_version`, `commitment_id`, `research_snapshot_id`, `holdout_snapshot_id`, `ingestion_record_content_hash`})) — **formule ACCEPTÉE exacte, aucune clé ajoutée** (vecteur V7) |
| Hash de contenu | `attachment_content_hash` = recette commune (`created_at` inclus) |
| Dépendance | `IngestionRecord` appartient à **E3-F** (non implémenté, 23.26). E3-E définit seulement un contrat minimal d'entrée `IngestionRecordRef` (`content_hash`, `holdout_snapshot_id`, plage, `complete`, `acquired_at`) ; l'attachment réel est BLOCKED (N17) |
| Refus | `ATTACHMENT_INVALID`, `…_COMMITMENT_MISMATCH`, `…_RANGE_MISMATCH`, `…_INGESTION_INCOMPLETE`, `…_DUPLICATE` (PROPOSÉS) ; « toute inégalité l'invalide » (ACCEPTED) |
| Garanties | G1, G2 ; le contenu des octets de `S_H` n'est jamais lu par E3-E (classes d'accès 23.7) |

### 5.6 `CommitmentVoidRecord`
| Attribut | Contenu |
|---|---|
| Identité / version | `gate_v_commitment_void_v1` (valeur **ACCEPTED**, 23.13 ; la révision 1 l'avait renommée à tort) ; `<campaign_dir>/commitment_void_record.json` (ACCEPTED 23.13), enregistrement exclusif et nominatif (ACCEPTED 23.8) |
| Schéma | `version`, `campaign_id`, `commitment_id`, `commitment_content_hash`, `cause` ∈ {`INGESTION_FAILED_PERMANENT`, `PROVENANCE_MISMATCH`, `SNAPSHOT_INTEGRITY`, `PROTOCOL_ERROR`, `TIME_PROOF_UNVERIFIABLE`, `RESERVATION_REFUSED`} (liste fermée ACCEPTED), `reservation_content_hash` (hex64 ou `null` = aucune réservation publiée ; PROPOSED, N14), `declared_by`, `detail`, `created_at`, `void_content_hash` |
| Règles (ACCEPTED) | refusé dès qu'une `CONSUMPTION` ou un `ReadIntent` existe ; la `RESERVATION` n'est **jamais libérée** (la fenêtre est perdue, avant ou après `ws`) ; une annulation avant toute réservation ne protège aucune fenêtre ; une erreur de snapshot ne donne jamais le droit de choisir un fichier de remplacement |
| Ambiguïté relevée (C-6, N14) | 23.8 dit que `RESERVATION_STALE` « est enregistrée avec la cause `RESERVATION_REFUSED` », alors que « refusée » désigne une réservation **non** publiée ; la liste de six causes est fermée. Proposition : conserver la liste fermée ; `reservation_content_hash` non nul distingue « publiée puis périmée » de « refusée avant publication » |
| Comptabilité (observabilité, revue B constat 4) | `SourceInterpretation` (B3) n'a aucun champ pour les nullités ; `AccountingViews.void_commitments` est une vue d'adaptation que rien ne fournit aujourd'hui. Sans **énumérateur strict** des nullités, le compteur est `NOT_OBSERVED` (non bloquant en `SYNTHETIC`, 23.29.5) et **supprimer un fichier void abaisse le compteur** (non conservateur). `abandoned_reservations` exige une `ClosingView` d'E3-J. Un engagement jamais réservé ni annulé n'est compté nulle part. Proposition : ajouter un énumérateur strict (tranche S-10) ou déclarer ces compteurs `NOT_OBSERVED` sans prétendre à l'observabilité (limite explicite) |
| Trou hérité de l'ADR (C-17) | 23.8 refuse la nullité seulement après `CONSUMPTION` ou `ReadIntent` ; un Claim **sans** `CONSUMPTION` (`CLAIM_ONLY`, 23.12) n'est pas couvert, donc une nullité pourrait masquer un droit déjà brûlé. Proposition : refuser aussi la nullité si un Claim existe (RED R-54) — à décider avec N14 |
| Garanties | G1, G2 ; **la nullité n'est pas dans le registre** (quatre types seulement) : supprimer ce fichier n'est pas détectable par le registre ; la protection de la fenêtre vient de la `RESERVATION`, pas de la nullité |

### 5.7 Témoin de tête du registre
| Attribut | Contenu |
|---|---|
| Rôle (ACCEPTED 23.6/23.9/23.10 6 bis) | détecter un retour en arrière du registre : après chaque `RESERVATION`/`ADMISSION`/`CONSUMPTION`/`REBIND`, le couple (`seq`, `record_content_hash`) de la tête est couvert par une preuve de temps de même niveau et **copié hors de l'hôte** ; pour une `RESERVATION`, la `ReservationTimeProof` fournit la preuve de temps (la copie hors hôte reste requise) |
| Schéma PROPOSÉ | `gate_v_registry_head_witness_v1` : `version`, `registry_id`, `instance_id`, `head_seq`, `head_content_hash`, `prev_witness_content_hash` (chaînage, `null` pour le premier témoin), `time_evidence` (même structure que 5.2 sur `head_content_hash`), `off_host_copy` {`location_id`, `copy_sha256`}, `created_at`, `witness_content_hash`. Aucun format de support n'est choisi (23.24) |
| Vérification (PROPOSÉE ; logique pure sur des octets lus par le lecteur strict, la lecture restant soumise à `R-REREAD`) | **ordre fixé** : (1) tête courante ≥ `max(w.head_seq)` sinon `REGISTRY_ROLLED_BACK` ; (2) puis, pour chaque témoin valide `w`, le slot `w.head_seq` de la chaîne relue a `record_content_hash` = `w.head_content_hash` sinon `REGISTRY_FORK` (la révision 1 donnait `FORK` avant `ROLLED_BACK` pour un témoin plus haut que la chaîne). **Source** : les témoins ne viennent que du support **hors hôte** (une restauration complète restaure aussi des témoins locaux, qui ne prouvent rien). **Chaînage** : chaque témoin porte `prev_witness_content_hash` (clé ajoutée au schéma) ; l'omission des témoins les plus récents reste indétectable, et c'est dit. En `SYNTHETIC` la détection est **nulle** (aucun support hors hôte) |
| Limite (ACCEPTED, 23.9) | tout enregistrement postérieur au dernier témoin et non référencé par un artefact connu est perdu par une restauration complète sans être détecté |
| Statut | modèle et détection PROPOSED ; émission, temps et copie hors hôte BLOCKED |

## 6. Matrice de dépendances et d'interfaces E3-D / E3-E / E3-J

`●` fourni · `○` consommé · `—` sans objet. « Relit » = relit le disque (`R-REREAD`).

| Capacité | E3-D (publié) | E3-E (proposé) | E3-J (futur) |
|---|---|---|---|
| Modèle/chaîne/lecture stricte du registre | ● `read_registry`, `RegistryChain`, `assemble_record` | ○ lit le registre pour les liaisons (préfixe, réservation) | ○ |
| `RESERVATION` : publication vérifiante | ○ moteur interne `_append_record` seulement | ● `verify_commitment` (relit) | ● API de publication qui rappelle `verify_commitment` **à chaque tentative** |
| `ADMISSION` : publication vérifiante | ○ idem (jamais exportée) | ● **chaque contrôle est une fonction d'E3-E qui lève un refus typé** ; `collect_admission_prerequisites` ne retourne qu'un rapport **descriptif** (faits et écarts), **sans booléen « ok »** (`R-NOBOOL`) | ● **E3-J exécute et répète** les sept contrôles de 23.27.4 après tout conflit de slot ; API de publication sous forme de **fabrique de corps** qui rappelle les vérificateurs à chaque tentative ; jamais `_append_record` ; liste blanche AST des importeurs de `_append_record` couvrant aussi E3-J |
| Attestation (schéma, hash, vérification) | ○ `attestation_hash` (hex64 jamais interprété) | ● 23.32 | ○ |
| Observation F1 | ○ `attestation_observation` (conteneur opaque) | ● construction, vérification, `history_digest` | ● double lecture avant publication ; reprise (`R-RECOVERY`) |
| Vue de recalcul post-`ADMISSION` | — | ● fonction `recompute_post_admission_view` (relit le registre et relance B3, ne renvoie que des scalaires) | ● étage exact, comparaison à l'étape 13 |
| Autorisation | ○ `authorization_hash` | ● 23.32.8 | ○ |
| Preuve de temps | ○ `time_proof_content_hash` | ● modèle + machine d'états ; vérificateurs BLOCKED | ○ ancrage en ligne, revérification hors ligne |
| Attachment / nullité | ○ `attachment_id`, `attachment_content_hash` | ● modèle ; réel BLOCKED (E3-F) | ○ |
| Témoin de tête | ○ (aucun) | ● modèle + détection | ○ émission/rejeu |
| Reprise / réutilisation d'une admission | ● `find_reusable_record` (rejeu d'une *publication* dans la même tentative ; gardes : `CONSUMPTION`, identité sémantique complète, reconfirmation) ; ● `read_authoritative_admission` (barrière, reconfirmation, `campaign_state`) | — | ● reprise = continuer l'ADMISSION autoritative + étape 11 bis (`R-RECOVERY`, 23.32.6.5) ; ● tentative neuve = candidat construit en direct, refus `CAMPAIGN_ALREADY_REGISTERED` si différent ; condition « aucun Claim ni ReadIntent local » (BLOCKED) |
| Publication des artefacts (attestation, autorisation, engagement, preuve) | ● primitive de lien d'E3-C | ● fonctions de publication qui relisent, calculent `seq` et hash, et **reconstruisent sur `SlotOccupiedError`** ; tentatives bornées fournies | ○ |
| Lecture d'`ADMISSION` autoritative | ● `read_authoritative_admission` (non probante) | ○ | ○ |
| `CONSUMPTION` | ● `publish_consumption` (SYNTHETIC) | — | ○ après le Claim d'E2 |
| Étape 8 (`*_STALE`), dérivation d'étage, `EXECUTION_VOID_<cause>`, `ClosingRecord` | — | — | ● |
| Autorité de classement sécurité/scientifique des refus | — | ○ fournit les causes | ● classe |

**Fonctions publiques PROPOSÉES d'E3-E** (noms provisoires ; + `publish_attestation`, `publish_authorization`, `publish_commitment`, `publish_time_proof` (relisent, calculent `seq`/hash, reconstruisent sur conflit) ; chacune relit le disque et ne reçoit ni booléen, ni callback, ni objet « vérifié ») : `read_commitment`, `verify_commitment`, `verify_reservation_time_proof`, `read_attestation`, `verify_attestation`, `build_attestation_observation`,
`verify_observation_against_disk`, `read_authorization`, `verify_authorization`, `derive_attachment`, `verify_attachment`, `verify_commitment_void`, `verify_head_against_witnesses`, `collect_admission_prerequisites`.

## 7. Invariants (liste d'acceptation)

I-1 Aucune fonction d'E3-E ne publie dans le registre ni n'appelle E2. I-2 Toute vérification relit le disque. I-3 Un hash correctement formé n'est jamais une autorisation. I-4 `REAL` refusé partout. I-5 Aucune lecture des octets de `S_H` ni du `FINAL_HOLDOUT`.
I-6 Aucune donnée de marché dans les tests (fixtures synthétiques uniquement). I-7 Aucune suppression ni réparation. I-8 Une préimage ne contient jamais le hash qu'elle produit. I-9 `created_at` et `attestor`/`authorizer` ne prouvent ni temps ni identité.
I-10 Une attestation n'autorise rien. I-11 Une vue de recalcul n'est jamais persistée comme A0. I-12 Les identités d'E3-A/E3-B/E3-D sont citées, jamais recalculées autrement ni modifiées.

## 8. Contradictions et ambiguïtés détectées

Liste complète et traitement : `0025-proposal-E3E-DECISIONS-PENDING.md` (C-1…C-36). Les décisions correspondantes sont dans `0025-proposal-E3E-N1-N20-FINAL-MATRIX.md`.

## 9. Annexe — recette de génération des vecteurs (indépendante du dépôt)

Le fichier `0025-proposal-E3E-HASH-VECTORS.json` a été produit par un script stdlib (`hashlib`, `json`, `unicodedata`) sans aucun import du dépôt, exécuté deux fois avec sortie identique, puis recoupé avec `gate_v_final_holdout_protocol._sha256_hex` (mêmes octets pour V1 et V6).
Résumé (révision 4) : V1 attestation ASCII (32 clés, préimage 2 010 octets), V2 attestant non ASCII + contre-vecteurs `ensure_ascii=True` et NFD, V3 `attestation_seq` et indépendance de l'ordre des clés, V4 indépendance de la valeur de la clé exclue, V5 observation F1 + contre-vecteur d'un slot altéré, V6 autorisation, V7 `attachment_id` (formule de l'ADR 23.8 avec le nom normatif de 23.13 ; entrées dans le JSON), V8 empreinte RFC 3161 (32 octets) + contre-vecteur, V9 SHA-256 des octets persistés d'une attestation et observation d'une chaîne à un slot (386 octets), V10 décimaux canoniques (grammaire, identité aller-retour, test de propriété sur 20 000 doubles, ambiguïté `10000` / `10000.0`). Les valeurs de remplissage sont `SHA-256` d'étiquettes ASCII (`label(x)`), reproductibles. Un futur test RED doit recalculer ces valeurs **sans** les importer d'un module de production, puis comparer au module.
