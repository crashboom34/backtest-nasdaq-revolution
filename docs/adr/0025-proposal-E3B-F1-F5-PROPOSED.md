# Proposition E3-B F1 / F5 pour l'ADR 0025 — NON NORMATIVE, NON ADOPTÉE

**Statut : PROPOSITION (2026-10-19). Aucune règle de ce fichier n'est en vigueur.** Le texte d'autorité reste
`docs/adr/0025-gate-v-validation-policy-v1.md` (dont l'addendum local 23.31). Ce fichier ne devient normatif que par une décision explicite de
l'utilisateur, suivie d'une intégration dans l'ADR (numéro proposé : 23.32). Il ne remplace rien et ne modifie aucune formule d'E3-A.

Sources de mesure : `tests/test_gate_v_exposure_attestation_phases.py` (caractérisation, fixtures synthétiques), `AI_HANDOFF.md` §56 et §57.
`REAL` = DISABLED / NOT QUALIFIED. `GATE V` = NON PASSÉE. `FINAL_HOLDOUT` = NON ACCÉDÉ.

---

## 0. Orientations de conception RETENUES (2026-10-19) — pour E3-D / E3-J, non normatives, non implémentées

Orientations données par l'utilisateur le 2026-10-19 après le rapport `AI_HANDOFF.md` §57. Elles remplacent les « décisions requises » de 1.3 et 2.2 par des
orientations de CONCEPTION. Elles ne sont pas des règles de l'ADR (aucun amendement n'est intégré) et **aucun code ne les implémente avant E3-D / E3-J** :
F1 reste `SPEC BLOCKED` pour le code, F5 reste une proposition de conception.

**F1 — vue de recalcul post-`ADMISSION`.**
1. Vue de recalcul **pure, hors de B3** (B3 et B4 publiés inchangés, pas de B3 v4).
2. **Preuve d'`ADMISSION` autoritative obligatoire** : la portée vient de l'enregistrement `ADMISSION` du registre (E3-D), lu et vérifié par E3-J. **Aucun témoin forgé,
   fourni ou non authentifié par un appelant ne vaut admission** (ce que reçoit B6 aujourd'hui, `AttestationPin`, n'en est pas une).
3. **Vérification du slot épinglé et de sa chronologie.** La chronologie n'est établie ni par une date de fichier ni par la seule déduction « `seq` supérieur ⇒ postérieur » de B6
   (qui suppose une `ADMISSION` conforme). Elle doit être prouvée par l'enregistrement `ADMISSION` lui-même (par exemple le plus haut `seq` observé à sa publication, voir
   atomicité ci-dessous). Un slot n'est « prouvé postérieur » que par cette preuve.
4. **Seules les attestations prouvées postérieures ET non épinglées peuvent être neutralisées**, et seulement pour le calcul SCIENTIFIQUE (`complete`, donc `inventory_id`).
5. **Les anomalies neutralisées restent consignées dans l'audit** (liste d'audit hors identités, transmise au `ClosingRecord`) : rien n'est effacé.
6. **Bloquent la poursuite, sans neutralisation possible** : l'altération du slot épinglé ; l'altération d'un slot historique antérieur au slot épinglé ; les fichiers inconnus ;
   les déclarations altérées ; les ruptures de chaîne. (Cela tranche les deux questions ouvertes de 1.3 : un slot antérieur altéré annule ; les autres écritures locales
   postérieures annulent toujours.)
7. **Aucun marqueur de vue ne doit devenir un A0 persisté ni contaminer une identité** : la vue (ou son marqueur) est refusée par B5 pour toute persistance, par E3-J avant
   l'`ADMISSION`, et n'entre dans aucune formule d'E3-A, de B4 ou de B5.
8. **Atomicité de lecture et protection contre les changements concurrents obligatoires** : la vérification « slot épinglé = plus haut `seq` » est refaite, ou le plus haut `seq` observé
   est enregistré, AU MOMENT de la publication de l'`ADMISSION` ; la lecture de la lignée, des slots et des octets épinglés est atomique ou stabilisée (double lecture identique) ; un
   changement observé entre deux lectures est un refus.
9. Étage propre exact fourni au recalcul (limite de la mesure 8) ; filtrage sur les observations du scan (anomalies de contenu de la racine de campagne courante) et jamais sur des
   chaînes de raisons (exigence 1 de 1.3, inchangée).

**F5 — hash de l'attestation.** Proposition de conception : **SHA-256 du JSON canonique compact (Décision 20.3), UTF-8, d'un record normatif validé**, **sans autoréférence** (la
préimage exclut la seule clé qui porte le hash). Les champs exacts, la préimage et le schéma seront définis avec **E3-E** ; la référence utilisée par l'`ADMISSION` avec **E3-D**.
**Aucune formule d'attestation n'est modifiée dans B6** (`AttestationPin` reste provisoire). L'adoption comme règle amendera 23.10 / 23.29.3 : décision future.

---

## 1. F1 — Slot d'attestation postérieur à l'`ADMISSION`

### 1.1 Conflit (mesuré)

23.29.3 : après l'`ADMISSION`, « un slot postérieur n'a aucun effet sur l'exécution en cours ». 23.27.3 : l'étape 13 de 23.17 compare
`inventory_id`, `static_sources_digest` et la projection de recouvrement, et un écart d'`inventory_id` est un « changement scientifique accepté »
(`EXECUTION_VOID_EXPOSURE_CHANGED`, terminal, sans lecture, mais Claim consommé). B3 v3 lit chaque `attestation_<seq4>.json` ; un slot illisible
donne `INFORMATIVE_UNRESOLVED`, donc `complete` faux, donc un autre `inventory_id`.

Mesures séparées (chaque ligne : une campagne synthétique ; « = base » = égal à la campagne sans attestation) :

| # | Scénario | Findings | `complete` | `inventory_id` | `static_sources_digest` | Projection | Anomalie d'audit (B3) | Réponse de B6 |
|---|---|---|---|---|---|---|---|---|
| 1 | slot valide, avant ADMISSION | 0 | vrai | = base | = base | = base | aucune | charge (pré-ADMISSION) |
| 2 | slot illisible, avant ADMISSION | 0 | **faux** | ≠ base | = base | = base | `INFORMATIVE_UNRESOLVED:…/attestation_0001.json` | refuse `ATTESTATION_INVALID` |
| 3 | slot valide ajouté après ADMISSION | 0 | vrai | = base | = base | = base | aucune | charge ; slot consigné `ATTESTATION_WITHOUT_EFFECT` |
| 4 | slot illisible ajouté après ADMISSION | 0 | **faux** | **≠ base** | = base | = base | `INFORMATIVE_UNRESOLVED:…/attestation_0002.json` | charge (« sans effet ») — **conflit F1** |
| 5 | attestation épinglée devenue illisible | 0 | faux | ≠ base | = base | = base | idem | refuse `ADMITTED_ATTESTATION_REPLACED` |
| 6 | slot ANTÉRIEUR au slot épinglé altéré après ADMISSION | 0 | faux | ≠ base | = base | = base | idem | charge ; slot consigné `ATTESTATION_NOT_REREAD` |
| 7a | épinglage forgé (hash faux / slot absent / chaîne inconnue) | 0 | vrai | = base | = base | = base | aucune | refuse `…_REPLACED` / `…_MISSING` |
| 7b | épinglage d'un slot ANTÉRIEUR valide, slot plus haut illisible | 0 | faux | ≠ base | = base | = base | idem | **charge** : B6 ne peut pas authentifier l'épinglage |
| 7d | épinglage dans une chaîne non terminale | — | — | — | — | — | — | refuse `ADMITTED_CHAIN_NOT_TERMINAL` (nouveau, 23.29.3) |
| 7e | épinglage sur la chaîne terminale, inventaire courant sans chaîne | — | — | — | — | — | — | refuse `ADMITTED_INVENTORY_CHANGED` (nouveau, revue A) |
| 8 | idem 3/4 avec les enregistrements propres du registre (RESERVATION, ADMISSION) absorbés à l'étage exact (`RESERVED`, `ADMITTED`) | 0 | idem | idem : égal à la campagne nue à l'étage exact | = base | = base | idem | idem (B6 n'a aucune entrée d'étage) |

Limites de la mesure 8 : le Claim (fichier d'E2) et la CONSUMPTION ne sont pas simulés ; `CLAIMED` et `CONSUMED` ne sont couverts qu'au niveau
de la formule d'E3-A (aucun enregistrement propre). L'étage n'est pas dans la formule mais décide quels enregistrements propres sont absorbés : un
mauvais étage change `inventory_id` (test `test_s8_the_stage_given_to_the_recalculation_matters…`) ; E3-J doit fournir l'étage exact.

Constats démontrés :

1. **Seul `complete` varie, donc `inventory_id`** (et `inventory_content_digest`, qui en dérive). Aucun finding, aucune exposition, ni
   `static_sources_digest`, ni projection ne bouge : un slot illisible n'est jamais une exposition scientifique nouvelle ; il n'y a donc aucune
   raison scientifique d'annuler une exécution pour lui.
2. **B3 n'a pas l'information** : `interpret_audit_roots` ne reçoit que des racines, des plafonds et la fenêtre (`test_b3_has_no_admission_input`).
   Il ne distingue ni la phase, ni le slot épinglé, ni un slot postérieur d'un défaut antérieur. Sa signature est verrouillée par un test publié.
3. **B6 a une information partielle et non authentifiée** : le slot épinglé fourni par l'appelant, vérifié par son hash (scénarios 5, 7a), et la
   structure des slots. Il ne peut pas prouver que ce témoin est celui de l'enregistrement `ADMISSION` du registre (scénario 7b).
4. **L'incomplétude de B3 a une valeur de détection** (scénarios 6 et 7b) : c'est la seule trace d'une altération d'un slot que B6 ne relit pas
   après l'`ADMISSION`. L'option (b) appliquée à toutes les attestations la supprimerait.
5. La chronologie n'est jamais prouvée par une date. Seule la déduction de 23.29.3 existe : avant l'`ADMISSION`, l'attestation valide est le slot de
   plus haut `seq`, que l'`ADMISSION` épingle ; un slot de `seq` supérieur est donc postérieur **si l'`ADMISSION` est conforme** (garantie d'E3-D / E3-J).

### 1.2 Options écartées

- **(a)** Note d'ADR « un artefact illisible sous `exposure/` est une incomplétude structurelle même après l'`ADMISSION` » : consacre la
  contradiction avec « aucun effet » en exception générale, et laisse un écrivain local annuler (Claim consommé) l'exécution d'une campagne.
- **(b)** B3 ignore toute anomalie d'attestation : supprime la détection du scénario 6/7b et retire un filet de B3 pour un défaut antérieur à
  l'`ADMISSION` (seul B6 resterait, et seulement s'il est appelé avant l'`ADMISSION`). Réserve honnête de la revue : B6 est de toute façon
  obligatoire pour obtenir un `DeclarationSet` et lit tous les slots avant l'`ADMISSION` ; (b) ne masquerait donc pas, en pratique, un défaut
  antérieur, et le rejet de (b) repose sur la valeur de détection d'une altération POSTÉRIEURE d'un slot antérieur au slot épinglé — un jugement, pas
  une conséquence de 23.29.3 (« seule l'attestation épinglée est pertinente »). Ce jugement est l'une des décisions demandées ci-dessous.
- **Portée de F1** : d'autres écritures locales postérieures à l'`ADMISSION` annulent aussi l'exécution quelle que soit l'option (fichier inconnu sous
  `exposure/` : `UNKNOWN_ENTRY` et `static_sources_digest` modifié ; déclaration illisible). F1 ne concerne que la classe « contenu d'un slot
  d'attestation postérieur ».

### 1.3 Proposition (à décider) — portée post-`ADMISSION` fournie par une source autoritative

**23.32.1 (PROPOSÉ).** *Avant l'`ADMISSION`, aucune règle n'est modifiée : tout slot illisible rend la racine incomplète (B3) et refuse la lignée
(B6). Lors d'un recalcul fait **après** la publication de l'`ADMISSION` (étape 13 de 23.17, reprise après crash), E3-J fournit à la vue de recalcul la
**portée d'attestation admise** `{inventory_id, seq}`, lue **exclusivement** dans l'enregistrement `ADMISSION` du registre (E3-D) et vérifiée par B6
(hash du fichier, structure, chaîne terminale). Dans cette vue, les raisons d'incomplétude `INFORMATIVE_UNRESOLVED` qui désignent
`exposure/<inventory_id de la portée>/attestation_<n>.json` avec `n` > `seq` de la portée n'entrent pas dans `incomplete_reasons`, donc pas dans
`complete` ni dans `inventory_id` ; elles sont consignées dans une liste d'audit `post_admission_attestation_anomalies`, hors identités, et
transmises au `ClosingRecord`. Toute autre anomalie reste inchangée : slot antérieur au slot épinglé, slot d'une autre chaîne, déclaration, A0 non
orphelin. Aucune date, aucune déclaration de l'appelant seule ne suffit : sans portée issue du registre, le comportement strict s'applique.*

Propriétés :
- ne crée aucune exposition, ne réécrit aucune identité d'E3-A ; `static_sources_digest` et projection restent comparés tels quels ;
- **la protection dépend entièrement de l'authenticité de l'enregistrement `ADMISSION` du registre (E3-D)**. Une portée forgée par un appelant (par
  exemple l'épinglage d'un slot antérieur valide, scénario 7b) retire l'incomplétude des slots postérieurs ; B6 ne vérifie alors que l'existence et le
  hash du fichier DÉSIGNÉ, ce qui ne prouve rien quand le faussaire choisit le fichier. Ni B3 ni B6 n'ajoutent de protection dans ce cas ;
- conserve la détection du scénario 6 (slot antérieur au slot épinglé toujours incomplet) ; celle du 7b n'existe que si la portée est authentique.

**Exigences sur le mécanisme, issues de la revue B (à respecter par toute mise en œuvre).**
1. *Filtrer sur les observations du scan, jamais sur des chaînes de raisons.* Les raisons `INFORMATIVE_UNRESOLVED:<racine>/<chemin>` n'indiquent ni la
   nature de l'anomalie (contenu illisible, entrée de mauvaise nature, erreur d'E/S) ni la campagne (deux racines de campagnes distinctes de même
   `inventory_id` produisent des chaînes identiques). La vue ne retire que les anomalies de CONTENU (JSON invalide, tronqué, clé dupliquée, constante non
   finie, BOM, UTF-8, profondeur, taille, type) des observations de règle `campaign.exposure.attestation` de la racine de campagne courante ; un
   répertoire, un lien ou une erreur d'E/S nommé comme un slot reste bloquant (même ensemble que `_ORPHAN_A0_ANOMALIES`).
2. *Marqueur contre la persistance.* La vue fabriquerait une `SourceInterpretation` que B3 n'a pas produite, à `complete` élargi, avec
   `semantics_version` v3 : B4 ne contrôle que le type et B5 ne refuse que `hooks_used`. Elle pourrait donc être assemblée puis persistée comme un A0
   normal, ou utilisée avant l'`ADMISSION`. Condition d'adoption : un marqueur obligatoire (champ par défaut `None`, additif et compatible avec la
   construction positionnelle des tests publiés de B3) que B5 refuse de persister et qu'E3-J refuse avant l'`ADMISSION` ; sans marqueur, « pas de v4 »
   ne tient pas.
3. *Étage exact.* Le recalcul doit utiliser l'étage de l'`ADMISSION` (voir limites de la mesure 8).

**Forme du mécanisme (choix à faire).**
- *(i) paramètre optionnel de `interpret_audit_roots`* : change la signature publique de B3, verrouillée par `test_b3_never_accepts_or_fabricates_observations`
  (test publié, à amender) ; non recommandé.
- *(ii) fonction pure hors de B3* (E3-J ou module dédié) qui reçoit la `SourceInterpretation` de B3 et la portée, retire exactement ces raisons,
  reconstruit une interprétation cohérente (`complete` ⇔ aucune raison) puis passe par B4 : **recommandée**, B3 / B4 publiés inchangés, comportement par
  défaut de B3 v3 identique, **pas de v4** ; le test de caractérisation `test_s4_*` bascule alors explicitement.
- *(iii) nouvelle disposition de racine* : modifie l'énumération `RootLayout`, les `rules_digest` enregistrés et la table de B5 ; non recommandé.

**Dépendances explicites (non simulées dans le code livré).** E3-D : l'enregistrement `ADMISSION` porte la référence d'attestation (voir F5) et l'`ADMISSION`
n'est publiée que si l'attestation épinglée est le slot de plus haut `seq` (`highest_attestation_slot`). E3-J : lit la référence dans le registre,
appelle B6 en mode post-`ADMISSION`, construit la portée, calcule la vue, compare `inventory_id` / `static_sources_digest` / projection.

Tests à écrire quand la décision est prise (RED d'abord) : les scénarios 3, 4, 6, 7b, 8 de `test_gate_v_exposure_attestation_phases.py` avec la vue ;
portée absente ⇒ comportement strict inchangé ; portée dont le hash ne correspond à aucun fichier ⇒ refus ; slot antérieur altéré ⇒ toujours incomplet.

**Statut des trois questions posées en 2026-10-19 (§57) : tranchées comme ORIENTATIONS de conception par la section 0** — (1) mécanisme (ii) retenu pour E3-D / E3-J avec les
exigences ci-dessus ; (2) un slot antérieur au slot épinglé, altéré après l'`ADMISSION`, annule ; (3) les autres écritures locales postérieures (fichier inconnu, déclaration altérée,
rupture de chaîne) annulent toujours. Ce ne sont pas des règles de l'ADR : elles ne le deviennent que par un amendement futur, avec E3-D / E3-J. **F1 reste `SPEC BLOCKED` pour le code.**

---

## 2. F5 — Hash d'épinglage de l'attestation

### 2.1 Conventions existantes (relevées)

| Artefact | Hash | Préimage | Emplacement |
|---|---|---|---|
| A0 | `inventory_content_hash` | SHA-256 du JSON canonique **compact** (Décision 20.3 : `sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False`) du record **sans** cette clé, `created_at` inclus | dans le record ; nom de fichier = hash |
| Déclaration | `declaration_content_hash` | idem pour l'enveloppe sans cette clé (inclut désormais `campaign_id`, 23.31.1) | dans le record |
| Sommet de chaîne | `tip_declaration_content_hash` | = `declaration_content_hash` de la dernière déclaration | dans l'attestation (épinglage) |
| Digest de lignée | `declaration_lineage_digest` | JSON canonique compact de la liste d'objets `{inventory_id, tip_seq, tip_declaration_content_hash}`, sans version ni balise (23.29.2) : la convention n'est donc pas uniforme | dans l'attestation (épinglage) |
| Octets persistés | — | `json.dumps(..., sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n"`, UTF-8, LF, point fixe vérifié | fichier |

23.29.3 parle d'un « fichier d'attestation épinglé par hash » sans fixer lequel. B6 utilise provisoirement le SHA-256 des octets du fichier
(`AttestationPin`), forme schéma-indépendante.

### 2.2 Recommandation normative

Aligner l'attestation sur la convention des deux autres artefacts : **hash de contenu du record, distinct de la représentation persistée**.

**23.32.2 (PROPOSÉ).**
- **Nature du record** : l'attestation `gate_v_exposure_attestation_v1` (nom déjà retenu en 23.29.3), objet JSON sans flottant, dont le jeu de clés exact
  est fixé par E3-E. Les clés suivantes sont **illustratives** (elles anticipent E3-E et ne le lient pas), à ajouter aux épinglages de 23.29.3 :
  `version`, `campaign_id`, `inventory_id`, `attestation_seq`, `created_at`, `attestor`, `attestation_content_hash`.
- **Préimage** : `attestation_content_hash = SHA-256( canonical_json( record privé de la seule clé "attestation_content_hash" ) )`, avec le
  `canonical_json` compact de la Décision 20.3, `created_at` inclus. La clé `version` dans la préimage sépare les domaines (A0, déclaration, attestation).
  `attestation_seq` dans la préimage rend deux slots de contenu autrement identique distincts.
- **Représentation persistée** : sérialiseur normatif unique de 23.29.4 (indenté), point fixe d'octets vérifié ; elle n'entre pas dans le hash.
- **Version sémantique** : `gate_v_exposure_attestation_v1` ; toute évolution de la préimage change la version. Une version **connue** mais
  antérieure donne une lecture historique intègre (comme 23.31.6 pour l'A0) afin qu'une attestation déjà admise reste vérifiable après une évolution
  du schéma ; une version **inconnue** est refusée.
- **Vérifications de relecture** (ordre) : JSON strict sans flottant ; clés exactes ; version connue ; hash stocké = hash recalculé ; point fixe
  d'octets ; répertoire = `inventory_id` ; nom du slot = `attestation_seq` ; `campaign_id` = campagne attendue. Les épinglages (A0, sommet de chaîne,
  digest de lignée, engagement, attachment, projection) restent évalués par E3-J, jamais par B6.
- **Référence portée par l'`ADMISSION`** : `{attestation_inventory_id, attestation_seq, attestation_version, attestation_content_hash}`, dans
  l'enregistrement `ADMISSION` du registre (E3-D), donc couverte par la chaîne de hashs du registre ; `attestation_version` nomme la recette de la
  préimage utilisée pour recalculer le hash.
- **Conflit ou altération** : fichier absent ⇒ refus (`ADMITTED_ATTESTATION_MISSING`) ; record bien formé dont le hash recalculé diffère de la
  référence ⇒ « remplacée » (`ADMITTED_ATTESTATION_REPLACED`, 23.10 / 23.29.3) ; mêmes octets logiques écrits sous une autre forme, ou record
  invalide ⇒ `ATTESTATION_INVALID` (point fixe, schéma), sans repli sur un autre slot. Les trois refusent ; seule l'étiquette de cause diffère.
- **Limite** : un hash recalculable sans secret prouve l'intégrité, pas l'authenticité ; l'identité de l'attestant reste déclarative (23.11).

**Pourquoi pas le seul SHA-256 du fichier ?** Par le point fixe, les deux formes sont en bijection et également fortes. Le hash de contenu est
retenu pour la cohérence (même recette pour A0, déclaration, attestation), l'auto-description du record et la séparation de domaine par `version`.
Le SHA-256 du fichier reste correct comme repli schéma-indépendant, mais il crée un second type de référence dans le registre.

### 2.3 Articulation et migration

- **E3-E** définit le jeu de clés, produit le record et calcule `attestation_content_hash`. **E3-D** enregistre la référence dans l'`ADMISSION`.
  **E3-J** lit la référence et la passe à B6.
- **B6** garde aujourd'hui `AttestationPin(inventory_id, seq, file_sha256)`, marqué PROVISOIRE. Quand E3-E existera, B6 recevra une variante
  `attestation_content_hash` et recalculera le hash du record relu ; aucune formule n'est introduite dans B6 avant le schéma.
- Aucun artefact d'attestation n'a jamais été publié : aucune migration, aucune rétroactivité.

**Statut (F5), 2026-10-19 : le hash de contenu du record est RETENU comme proposition de conception** (section 0) ; les champs exacts, la préimage et le schéma seront définis avec E3-E,
la référence de l'`ADMISSION` avec E3-D. L'adoption comme règle exige un amendement de 23.10 / 23.29.3 (« fichier épinglé par hash ») : ce n'est pas une précision rédactionnelle.
B6 conserve la forme provisoire et E3-D / E3-E ne doivent pas figer de référence avant cet amendement.

---

## 3. Contrat d'interface E3-D → E3-J → B6 (à respecter, non simulé)

| Étape | Acteur | Fournit / vérifie | B6 vérifie |
|---|---|---|---|
| Avant `ADMISSION` | E3-J | appelle B6 avec `admitted_attestation=None` ; exige que le slot candidat soit `highest_attestation_slot` | tous les slots, lignée, campagne, pas de flottant |
| Publication de l'`ADMISSION` | E3-D | enregistre la référence d'attestation (F5) dans le registre ; **exigence d'atomicité** : revérifie « slot épinglé = plus haut `seq` » AU MOMENT de la publication, ou enregistre le plus haut `seq` observé dans l'`ADMISSION` (sinon un slot écrit entre le contrôle de B6 et la publication serait classé « postérieur » à tort) | — |
| Après `ADMISSION` (étape 13, reprise) | E3-J | lit la référence dans le registre, l'envoie comme `AttestationPin` | fichier présent, octets égaux, structure, chaîne terminale (`ADMITTED_CHAIN_NOT_TERMINAL`) |
| Recalcul d'inventaire | E3-J | applique F1 si adopté (portée issue du registre) | — |

**B6 ne garantit pas** : l'authenticité du témoin d'admission, la chronologie réelle des slots, la validité d'une attestation, l'évaluation de ses
épinglages.

---

## 4. Conditions de refus avant et après Claim / `CONSUMPTION` (conception, non normative)

Deux classes, jamais confondues :
- **Refus de sécurité** : intégrité, authenticité ou stabilité non établies (artefact altéré, absent, inconnu, rompu, témoin non authentifié, lecture instable). Aucune conclusion
  scientifique n'en est tirée. **La vue F1 ne neutralise jamais un refus de sécurité.**
- **Changement d'exposition scientifique** : l'ensemble pertinent, `static_sources_digest`, la projection ou `inventory_id` diffèrent par les findings ou par une incomplétude non
  neutralisable. C'est une information d'exposition nouvelle (23.27.4), pas un défaut d'intégrité.

| Phase (23.17) | Condition | Classe | Issue (états définis par l'ADR) |
|---|---|---|---|
| Avant l'`ADMISSION` (étapes 8 à 11) | tout slot d'attestation illisible ; déclaration altérée ; chaîne rompue ; fichier inconnu ; A0 épinglé illisible ou absent ; campagne ≠ attendue ; lecture instable | sécurité | refus ; rien n'est consommé ; recalcul permis (23.18, ligne « Inventaire → attestation → autorisation ») |
| Avant l'`ADMISSION` | `static_sources_digest`, projection ou `inventory_id` (par findings) changés | scientifique | attestation périmée ; `RESERVATION_STALE` / `ADMITTED_STALE` selon l'enregistrement existant (23.10, étape 8 ; 23.27.4) |
| Après l'`ADMISSION` durable, avant le Claim | attestation épinglée absente ou différente (« remplacée ») ; slot historique antérieur altéré ; fichier inconnu ; déclaration altérée ; rupture de chaîne ; témoin d'admission non authentifié ou forgé ; changement observé entre deux lectures | sécurité | refus ; l'admission reste et réserve la fenêtre ; aucun Claim (23.10, « Crash avant le Claim ») |
| Après l'`ADMISSION`, avant le Claim | `static_sources_digest`, projection ou `inventory_id` (par findings) changés ; chaîne terminale ou inventaire courant changés | scientifique | `ADMITTED_STALE`, terminal pour E3 (seule une décision humaine peut le déclarer nul) |
| Après l'`ADMISSION` | slot d'attestation **prouvé postérieur** (preuve de l'`ADMISSION`) et non épinglé, valide ou illisible | neutralisé (calcul scientifique seulement) | aucun refus ; anomalie consignée dans l'audit ; le Claim n'est pas retardé par lui |
| Après le Claim et la `CONSUMPTION`, avant le `ReadIntent` (étape 13) | `static_sources_digest`, projection ou `inventory_id` (par findings) changés ; chaîne terminale changée | scientifique | `EXECUTION_VOID_EXPOSURE_CHANGED`, terminal, sans lecture, Claim consommé (23.10, étape 8 ; 23.17) |
| Après le Claim et la `CONSUMPTION`, avant le `ReadIntent` | mêmes conditions de sécurité que ci-dessus | sécurité | aucune lecture (aucun `ReadIntent`) ; état terminal `EXECUTION_VOID_<cause>` (seule graphie admise, 23.13) ; **le nom de la cause de sécurité est à fixer par E3-J, il n'est pas inventé ici** ; Claim consommé, aucun retry (23.18) |
| Après le Claim et la `CONSUMPTION` | slot prouvé postérieur et non épinglé | neutralisé | idem : aucun refus, anomalie consignée |
| Après le `ReadIntent` | — | hors périmètre de F1 | fenêtre traitée comme exposée, aucun retry (23.17 étape 14, 23.18) |

Rappels : la comptabilité des essais n'est jamais comparée après l'`ADMISSION` (23.27.3) ; un compteur ne peut pas brûler une fenêtre. Les refus typés actuels de B6
(`ATTESTATION_INVALID`, `ADMITTED_ATTESTATION_MISSING` / `_REPLACED`, `ADMITTED_CHAIN_NOT_TERMINAL`, `ADMITTED_INVENTORY_CHANGED`, `UNKNOWN_ENTRY`, `DECLARATION_INVALID`, `FORK`…)
sont des causes de SÉCURITÉ au sens ci-dessus, sauf `ADMITTED_CHAIN_NOT_TERMINAL` / `ADMITTED_INVENTORY_CHANGED` et `INVENTORY_REVERSION`, qui signalent un changement d'exposition
(classe scientifique) : E3-J les classe, B6 ne tranche pas l'état terminal.
