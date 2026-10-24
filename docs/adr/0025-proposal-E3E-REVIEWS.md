# Rapport des revues indépendantes E3-E — NON NORMATIF

**Statut : rapport de revue (2026-10-20), mission « E3-E design gate ».** Six relectures indépendantes **en lecture seule** (sous-agents `claude-sonnet-5-5`, aucun fichier du dépôt modifié) ont porté sur les propositions `0025-proposal-E3E-*`. Ce rapport ne **valide rien** : une convergence entre agents n'est pas une acceptation (mission § 8) ; seules les décisions `N1…N20` de l'utilisateur rendent une règle normative.
`REAL` = DISABLED / NOT QUALIFIED · `GATE V` = NON PASSÉE · `FINAL_HOLDOUT` = NON ACCÉDÉ · F1 = SPEC BLOCKED · F5 = PROPOSED.

| Revue | Angle | Type d'agent | Durée journal | Recommandation |
|---|---|---|---|---|
| **A** | sécurité, intégrité, temporalité, concurrence, reprise | `ecc:security-reviewer` | ≈ 7 min 30 s | « pas prêt en bloc » ; F5 acceptable après corrections mineures, **F1 à garder bloquée**, preuves de temps et témoin de tête à garder bloqués |
| **B** | validité scientifique, leakage, reproductibilité, rétrocompatibilité | `general-purpose` | ≈ 14 min 30 s | « **bloqué** » : trois défauts de spécification à corriger avant toute décision de l'utilisateur |
| **C** (re-revue de la révision 2) | vérifier que les corrections sont réelles et n'en introduisent pas de nouvelles | `general-purpose` | ≈ 6 min 50 s | « aucun défaut **bloquant** de conception » ; deux contradictions élevées (restes de la révision 1) et des précisions → révision 3 |
| **D** (4e relecteur, révision 3 complète) | tout : N1–N20, C-1–C-23, schéma, vecteurs, concurrence, préconditions d'E3-D, plan TDD | `general-purpose` | ≈ 21 min 24 s | « la révision 3 n'est pas soumissible telle quelle » : N4, N7, N9, N10, N18, N19 à réécrire → révision 4 |
| **E** (5e, delta révision 4) | idem, centré sur les réécritures | `general-purpose` | ≈ 12 min 30 s | architecture correcte ; 6 assertions fausses ou imprécises → révision 5 |
| **F** (6e, delta final révision 5) | vérifier les corrections de E | `general-purpose` | ≈ 10 min 50 s | **aucun défaut bloquant ni élevé** ; 5 constats moyens, dérives textuelles → révision 6 |

La révision 3 (qui traite les constats de C) a ensuite été relue en entier par un **quatrième relecteur indépendant (D)** : voir la section 5. La révision 4 corrige ses constats ; son **delta** a été confié à un **cinquième relecteur (E)** (section 6). Contrôles mécaniques complémentaires (non assimilés à une revue) : 32 clés du tableau = 32 clés du vecteur V1 ; vecteurs recalculés deux fois ; recoupement avec `_sha256_hex` et `_chronology_record` d'E3-A.

## 1. Constats de la revue A et traitement

| # | Sévérité | Constat | Traitement |
|---|---|---|---|
| A1 | **BLOQUANT (N4)** | L'argument « la fenêtre dernière-lecture→`link` est sans droit conféré » est **faux** : le Claim d'E2 est irréversible et R-34 traite déjà une attestation plus récente comme une supersession | **Reconnu et corrigé** : phrase supprimée ; garde pré-Claim `PCG` bloquante (option A) ou application littérale de 23.29.3 (option B) ; sections de l'ADR à amender listées (N4) |
| A2 | élevé | `R-RECOVERY` supprimait des garde-fous d'E3-D (refus après `CONSUMPTION`, comparaison sémantique complète, reconfirmation) | Corrigé : candidat reconstruit **avec l'observation recopiée** + `find_reusable_record` + `PCG` ; états dérivés ; reprise après Claim par lecture autoritative (N7) |
| A3 | moyen | La double lecture précédait le travail lourd : elle élargissait la fenêtre | Corrigé : dernière E/S avant le retour du corps (23.32.6.2) |
| A4 | moyen | Vérifier puis hacher non interdit ; lectures sans `lstat`/`O_NOFOLLOW`/plafonds | Corrigé : `R-ONEBUFFER`, `R-STRICTREAD`, plafonds provisoires |
| A5 | moyen | `R-REPLAY` incomplet ; seconde vérification sans information indépendante | Corrigé et formulé honnêtement |
| A6 | moyen | Témoin de tête : ordre `FORK`/`ROLLED_BACK` ambigu, source des témoins, omission des plus récents | Corrigé (ordre, source hors hôte, chaînage, limites) |
| A7 | moyen | Phrases qui survendent (chaîne de hashs, « toute modification ») | Corrigé ; tableau « ce que le design protège » |
| A8 | moyen | `collect_admission_prerequisites` : risque de booléen « ok » ; qui exécute quoi | Corrigé : `R-NOBOOL`, E3-J exécute et répète, liste blanche AST |
| A9 | moyen | `SYNTHETIC_FIXTURE` donne `VALID` sans marqueur de mode dans l'attestation | Corrigé : clés `time_proof_type`, `registry_mode` |
| A10 | moyen | RED R-40 non exhaustive | Corrigé : R-56, R-57, R-58, autorisations multiples (R-52) |
| A11–A12 | faible | Unicode (C1, bidi, zéro-largeur…) ; incohérences documentaires | Corrigé (catégories Unicode) ; `REVIEWS.md` créé ; comptes corrigés |
| A13 | info | La vue post-`ADMISSION` corréle des chaînes de raison | Corrigé : `incomplete_causes` structuré (B3 v4, N19) |

## 2. Constats de la revue B et traitement

| # | Sévérité | Constat | Traitement |
|---|---|---|---|
| B1 | élevé | Les faits d'entrée de la classification (marge, `s0_max_time`…) n'ont aucune origine ; `classification_id` en dépend | Corrigé : table 23.32.4 bis, clés 22–24, N20 |
| B2 | élevé | La vue F1 « pure sur E3-A sans B4 » est irréalisable avec les entrées listées et écarte l'orientation du 2026-10-19 sans décision | Corrigé : passage par B4, N19 |
| B3 | élevé | Noms **normatifs** de l'ADR 23.13 renommés à tort ; V7 en dépend | **Reconnu et corrigé** ; V7 = `dec3d4f9…` avec le nom de l'ADR ; autorisation : N10 |
| B4 | moyen-élevé | `void_commitments` / `abandoned_reservations` non observables ; supprimer un void abaisse le compteur | Documenté : énumérateur strict ou `NOT_OBSERVED` assumé (spec 5.6, C-23) |
| B5 | moyen | Ordre des tranches faux (S-3 dépendait de S-8/S-9/S-10), cas RED mal rattachés | Corrigé : S-3a/S-3b, alignement du plan |
| B6 | moyen | Périmètre B3 v4 incomplet ; tests publiés à amender | Corrigé : périmètre, tests listés (N8) |
| B7 | moyen | **Défaut latent entre modules publiés** : `RegistryRecordFact.seq >= 1` vs registre numéroté depuis 0 | Vérifié par nous (`gate_v_exposure_inventory.py:163`) ; C-16, tranche S-0b, RED R-55 — **décision utilisateur** |
| B8 | moyen | C-1 inexact (23.27.7 place déjà attestation/autorisation dans E3-E) ; N5/N7 partiellement tranchés par l'ADR ou l'orientation | Corrigé : C-1, N15, N5, N7 |
| B9 | moyen | N18 insuffisant (grammaire, correspondance avec le moteur) | Étendu ; limite explicite sur les hashs hérités |
| B10 | moyen | Ré-attestation et éligibilité non écrites | Corrigé : éligibilité `admission_refusals == ()`, R-51, limite 23.32.12.7 |
| B11 | faible | Nullité après un Claim sans `CONSUMPTION` (trou hérité de l'ADR) | C-17, R-54 (N14) |
| B12–B13 | faible | Incohérences documentaires ; reproductibilité résiduelle (tri UTF-16…) | Corrigé (V9, dates cohérentes, clés ASCII) ; NFC et version Unicode : limite 23.32.12.8 |
| B14 | info | Aucun consommateur ne lit le holdout avant le Claim | Confirmé |

## 3. Constats de la re-revue C (révision 2) et traitement (révision 3)

| # | Sévérité | Constat | Traitement |
|---|---|---|---|
| C1 | élevé | La ligne RED R-14 est restée en révision 1 | Scindée en R-14a (avant Claim) et R-14b (après Claim) |
| C2 | élevé | Spec § 2 affirmait encore que la reprise n'utilise pas `find_reusable_record` | Réécrit comme 23.32.6.5 |
| C3 | moyen | `reconfirmation_reliable` n'est pas observable après un crash (propriété en mémoire) | Restreint à la reconfirmation **courante** ; l'échec de `fsync` d'un processus mort est une **limite assumée** (R-59 corrigée) |
| C4 | moyen | N5 survendait encore | Réécrit avec la portée exacte |
| C5 | moyen | La `PCG` s'appuie trop favorablement sur 23.10 ; chaîne relue non précisée ; détection du Claim BLOCKED | Sections à amender listées ; chaîne terminale vérifiée ; dépendance E3-J explicitée |
| C6 | moyen | `chronology_facts_digest` non défini ; faits inconnus inexprimables | Défini sur `_chronology_record` d'E3-A ; vecteur **calculé** ; faits inconnus ⇒ non publiable |
| C7 | moyen/faible | La règle Unicode dépend de la version de `unicodedata` ; `attestor` vide | `Cn` retiré, non vide après `strip()`, limite 23.32.12.8 |
| C8–C13 | faible | Désalignement RED/tranches ; schéma du témoin ; N19 absent du § 4 ; noms (`assemble_exposure_inventory`, `AccountingViews`) ; lieu de consignation de l'audit | Corrigés |
| C14 | info | Dates de V1/V6 antérieures à `we` | Corrigées (2026-07-02) ; hashs régénérés |

## 4. Ce qui a été vérifié exact par les relecteurs (et par nous)
- Vecteurs recalculés indépendamment par A, B et C à partir des règles (sans réutiliser notre script) : concordance ; recoupement par nous avec `_sha256_hex` d'E3-A.
- B3 v3 : `_CAMPAIGN_RULES` = `plan.json` + Claim + `exposure/` ; fichiers inconnus = incomplétude (test publié). `TempNaming` = `EXPOSURE`, `REGISTRY`. `admission_id` inclut `attestation_observation`. `AttestationPin` = `(inventory_id, seq, file_sha256)`. Plafonds de l'opaque : 16 384 octets, profondeur 8 (observation : 386 octets).
- L'invariance de l'`inventory_id` entre `RESERVED` et `ADMITTED` (`partition_own_records`).

## 5. Revue D (quatrième relecteur, révision 3 complète) et traitement (révision 4)
Relecteur n'ayant participé à aucune revue précédente (`general-purpose`, `claude-sonnet-5-5`, ≈ 21 min 24 s au journal), lecture seule, calculs en mémoire. Verdict : « la révision 3 n'est pas soumissible telle quelle ; le bloc F5 est cohérent et recalculable ; N4, N7, N9, N10, N18 et N19 doivent être réécrits ».
Nous avons **vérifié nous-mêmes** les assertions de code avant de les adopter : le sérialiseur d'E3-C refuse les flottants ; B2 impose le motif d'orphelin `EXPOSURE` à toute règle d'orphelin ; les labels de racine sont uniques (`DUPLICATE_ROOT_LABEL`) ; `confirm_published_slot` est générique ; un test publié attend `seq=0` refusé.

| # | Sévérité | Constat | Traitement |
|---|---|---|---|
| D1 | élevé | N4 option A (`PCG`) : appuie à tort sur 23.10 (c'est un amendement), ne couvre que les attestations (une *déclaration* durcissante entre l'ADMISSION et le Claim échappe à l'observation), crée un état hors de la liste fermée de 23.18, offre un levier de gel ; la re-vérification des faits comble le vrai trou de 23.17 | **Reconnu : ma recommandation initiale (A) est abandonnée.** Option **C** (étape 11 bis : contrôles 1,3,4,5,6,7 de 23.27.4 sur artefacts épinglés + slot épinglé + `history_digest` + durabilité) ; slots postérieurs sans effet ; 23.29.3 et 23.10 non amendés ; 23.17 amendé de façon additive |
| D2 | élevé | `R-RECOVERY` non exécutable : `find_reusable_record` compare tout le corps ; recopier l'observation ne suffit pas (`attestation_hash`/`authorization_hash` viennent de l'attestation « courante ») ; et le motif de rejet de `read_authoritative_admission` (révision 1) était faux | Corrigé : la reprise **continue** l'ADMISSION autoritative, aucun candidat reconstruit (N7, R-69) |
| D3 | élevé | Durabilité des artefacts épinglés non exigée avant l'ADMISSION | Corrigé : principe 8 de 23.32.0, R-68 |
| D4 | élevé | N18 : l'alternative « nombres JSON » est impossible (`serialize_normative_json` refuse les flottants) | Corrigé : alternative retirée ; chaînes décimales typées ; V10 ; R-73, R-74 |
| D5 | moyen-élevé | N9 : un nouveau `TempNaming` oblige à modifier B2 et les digests | Corrigé : `TempNaming.EXPOSURE` réutilisé ; **E3-E0b / S-6 supprimées** ; C-26 |
| D6 | moyen | `incomplete_causes` inutile et contraire à l'orientation « pas de B3 v4 pour F1 » : les raisons se dérivent des observations structurées des scans | Corrigé : champ supprimé ; B3 v4 minimal (S-5a) distinct de F1 ; S-5b optionnel |
| D7 | moyen | N19 (a1) insuffisant | Corrigé : mécanisme (a3) scalaires seulement, relit le registre, plus (a2) optionnel (N19b) |
| D8 | moyen | Un fait transitoire (E/S) devenait une péremption définitive | Corrigé : trois classes SÉCURITÉ / PÉREMPTION / RÉESSAYABLE (principe 4, R-76) |
| D9 | moyen | N10 : règles manquantes (quelle autorisation avant l'ADMISSION, expiration/révocation, slot illisible après l'ADMISSION, recherche par hash) | Corrigé : contrat complet 23.32.8, R-75 |
| D10 | moyen | Chemin critique omettait S-5 ; lignes de tranche désalignées | Corrigé (plan, handoff § 65) |
| D11 | faible | `attachment_id` de V1 ≠ V7 ; contre-vecteur V5 non recalculable ; fragment dupliqué ; redondance de l'observation ; `anchor_margin_seconds` sans borne ; `Cn` | Corrigé / assumé (V1 et V7 identiques, octets du contre-vecteur fournis, redondance volontaire, E3-A juge `≤ 0`) |
| D12 | faible | Statuts : P9/P13 de la matrice E3-D sont PROPOSED ; N5/N6/N13/N16 recoupent l'ADR ou les orientations ; N11 amende 23.6 | Corrigé dans la matrice (colonne « État ») |
| D13 | info | Contradictions manquantes C-24…C-28 | Ajoutées |

Recommandation de D sur N4 : « ni A ni B » (retenue : C) ; sur C-16 : `seq < 0` et amendement du test, aucun décalage +1 (retenu) ; sur N10 : slots avec règles complètes (retenu) ; sur B3 v4 : minimal, sans champ (retenu). Lots proposés par D : N1, N2+N20, N3, N16, C-16, S-5a d'abord ; F1, N9, N10, N18 après réécriture — **réécritures effectuées en révision 4, puis soumises à la relecture du delta (section 6)**.

## 6. Revues E et F (deltas des révisions 4 et 5) et traitement

**Revue E (cinquième relecteur, delta de la révision 4).** Aucune voie d'abandon sélectif ou de gel nouvelle ; l'option C est supérieure à A. Constats traités en révision 5 (après vérification par nous du code et de l'ADR) :

| # | Sévérité | Constat | Traitement |
|---|---|---|---|
| E1 | élevé | `campaign_state == ADMITTED` n'exclut pas un Claim acquis (le Claim n'est pas dans le registre) : 11 bis rejoué après un Claim annoncerait à tort `ADMITTED_STALE` | Précondition « aucun Claim ni `ReadIntent` local » (E3-J) avant 11 bis et la reprise ; refus `AlreadyInProgressOrConsumed` / `CLAIM_ONLY` ; R-79 |
| E2 | élevé | Péremption de l'autorisation (« plus terminale ») rétablissait la garde `PCG` après l'ADMISSION | « terminale » avant, « épinglée par hash » après ; R-80 |
| E3 | élevé | B3 v4 minimal ne rend pas un dossier V2 réel complet (`manifest.json`, `validations/`, `technical_failure.json`, `manifest.update.lock`, Q-2) | C-29 ; Lot 1 **qualifié** (bout en bout non démontré) ; information manquante nommée (§ 4 de la matrice) |
| E4 | moyen | « 23.27.3 impose déjà ces contrôles » surévalué (« seuls » trois contrôles) | N4 → PARTIEL ; **23.27.3 amendé** |
| E5 | moyen | `ADMITTED_STALE` utilisé au-delà de sa définition (23.10 étape 8) | **23.10 étape 8 / 23.18 amendés** (23.32.11) |
| E6 | moyen | N18 : `"-0"` passait la grammaire et l'identité aller-retour ; type non imposé ; enveloppe non documentée | grammaire sans `-0`, `canon` explicite, type par champ, enveloppe et échantillonneur documentés ; R-81 |
| E7 | moyen | N19 : `SourceInterpretation` reçue par valeur ; étage « dérivé » ≠ orientation 9 ; `LONE_SURROGATE` omis | la fonction relance B3 ; écart déclaré ; anomalie ajoutée |
| E8 | moyen | N3 (Lot 1) impose `history_digest` (N5, Lot 2) ; amendements manquants (23.4, 23.31.2/6) | N5 déplacée au Lot 1 ; amendements ajoutés |
| E9 | moyen/faible | N7 : une tentative neuve identique pouvait contourner 11 bis ; nom du refus de R-60 | « si une ADMISSION existe, toujours la reprise » ; nom précisé |
| E10 | faible | Rattachements RED/tranches, obsolescences, noms de tags B3 v4, plafond 9999, trou de densité des autorisations | corrigés |

**Revue F (sixième relecteur, delta final de la révision 5).** *Verdict : aucun BLOQUANT ni ÉLEVÉ ; soumissible après corrections de texte.* V10 recalculé en mémoire (valides, invalides, propriété sur 20 000 doubles, énumération exhaustive des chaînes de 5 caractères : bijection), V1/V5/V6/V9 et comptes de clés exacts, R-01…R-81 et C-1…C-34 contigus, 12 clauses d'amendement présentes.

| # | Sévérité | Constat | Traitement (révision 6) |
|---|---|---|---|
| F1 | moyen | « `ADMITTED_STALE` terminal, consigné, jamais levé » non enforçable (état dérivé, audit non garde) | reformulé : dérivé, recalculé à chaque tentative ; marqueur persisté = amendement distinct non proposé (C-36) |
| F2 | moyen | R-14b et R-79 donnaient deux attendus pour la même situation | R-14b = refus de reprise ; le tableau des slots postérieurs ne vise que l'étape 13 |
| F3 | moyen | N18 : « type par champ » sans table ; `fullmatch`, ASCII, booléen absents de 23.32.9 | table des champs, règle de `oos_parameters`, `fullmatch`, cas `"0.5\n"` dans R-73 |
| F4 | moyen | Écarts aux orientations du 2026-10-19 non déclarés (« pure » ; neutralisation étendue aux autorisations) | écarts déclarés ; **extension aux autorisations retirée** (option de N6) ; C-35 |
| F5 | moyen | Traçabilité : § 6 vide, renvois 23.32.10.x obsolètes | complété et corrigé |
| F6–F8 | faible/info | dérives textuelles (révision, comptes de revues, R-49 (c), R-81/R-80 absents de la matrice, phrase cassée du plan, « S-5 » sans limite, S-1 « bloquée par N1 », Lot 1 vs S-8, classe de refus des contrôles 5–7, Claim d'une copie, entrées `limits` de N19, `hooks=None`, `replace` et `complete`) | corrigés ou déclarés |

**La révision 6 (nettoyage textuel après la revue F) n'a PAS été relue par un septième relecteur** : contrôles mécaniques seulement (comptes, références, absence d'usages courants d'éléments abandonnés). Elle ne change aucune décision de conception.

## 7. Ce qui reste ouvert ou non vérifié (honnêtement)
1. Non exécuté : les suites de tests, le comportement Linux/`REAL`, l'autorité de temps (non choisie), le comportement de la reprise sur du code réel (E3-J n'existe pas).
2. Décisions que seul l'utilisateur peut prendre : N1…N20 et C-16 (matrice finale) ; en particulier **N4** (option C, qui amende 23.17 de façon additive), **N19** (mécanisme de la vue F1) et **C-16** (correction d'un module publié et d'un test publié).
3. Limites de conception acceptées explicitement : observation F1 non indépendamment vérifiable ; fenêtre [recontrôle 11 bis, Claim] irréductible ; échec de `fsync` d'un processus mort indétectable ; authenticité déclarative ; omission du dernier témoin indétectable ; NFC dépendante de la version Unicode.
4. Aucune des corrections n'adopte une règle : tout reste `PROPOSED`.
