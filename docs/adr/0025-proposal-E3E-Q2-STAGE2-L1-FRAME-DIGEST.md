# K1 Étape 2 — lot L1 : moteur d'empreinte de trame (`gate_v_frame_digest.py`) — NOTE TECHNIQUE LOCALE, NON NORMATIVE

**Statut (2026-10-24).** Implémentation du lot L1 du contrat R9 (`0025-proposal-E3E-Q2-STAGE2-CONTRACT-PROPOSED.md`, **PROPOSED, non accepté**). L'autorisation de l'utilisateur est limitée à ce module pur, à ses tests et à cette note ; elle n'accepte aucune des décisions D1-D9. Aucun commit, aucun push. `REAL` = DISABLED / NOT QUALIFIED · `GATE V` = NON PASSÉE · `FINAL_HOLDOUT` = NON ACCÉDÉ.

## 1. Ce que le module démontre — et ce qu'il n'affirme pas
Il calcule des **faits** sur des octets ou des colonnes typées fournis par l'appelant :
1. `source_sha256` : SHA-256 des **octets bruts** d'un snapshot S0 (identité `local_csv:sha256:<h>` existante) ;
2. `frame_sha256` : empreinte de la **trame décodée** (R9 3.2), indépendante de toute sérialisation pandas ;
3. bornes temporelles de la trame : première ouverture, dernière ouverture, **clôture exclusive de la dernière barre** (ouverture + durée **déclarée**).

Il **n'affirme pas** : que S0 est le seul fichier chargé, que tous les workers utilisent cette trame, que l'optimiseur ne recharge rien (le repli `optimizer._worker_run_single` existe), que la stratégie ne lit rien d'autre, qu'une exécution est exposée ou non, qu'une campagne est admissible. **Aucun verdict** (`FRESH`, `NO_OVERLAP`, admission, Claim) n'existe dans l'API ; un test refuse tout champ de ce type.

## 2. API publique (figée par `__all__` et un test)
| Nom | Rôle |
|---|---|
| `FrameColumn(name, kind, values)` | colonne typée explicite : `time_us` (µs depuis 1970, naïf interprété UTC), `i64`, `f64` ; `values` est un `tuple` ; types Python **exacts** (ni `bool`, ni `int` dans un `f64`) |
| `compute_frame_digest(columns)` | SHA-256 de la préimage R9 3.2 |
| `compute_frame_facts(columns, declared_bar_seconds)` | `FrameFacts` (digest, lignes, colonnes, durée déclarée, trois instants) ; `to_record()` = objet `frame` de R9 5.1 (9 clés, sans flottant) |
| `columns_from_csv_bytes(raw)` | octets CSV → colonnes (dialecte strict, types inférés du **texte**) |
| `compute_s0_frame_facts(raw, declared_bar_seconds)` | `S0FrameFacts` : octets bruts (hash, taille, snapshot id) + trame ; `to_record()` = objet `S0FrameFacts` de R9 |
| `FrameRefused` / `FrameRefusal` | refus typé, vocabulaire fermé (22 codes) ; aucune entrée hors contrat ne produit de fait |

Pureté : stdlib seule (`csv, hashlib, io, json, math, re, struct, datetime, dataclasses, enum`), aucun accès disque ou réseau, aucun état global mutable ; vérifié par analyse AST, par exécution avec `open` et `socket` désactivés, et par un interpréteur neuf (`-I`) sous trois `PYTHONHASHSEED`.

## 3. Politiques R9 explicitées, ambiguïtés et écarts (à trancher lors de l'acceptation de L2/D3)
| Sujet | Décision de L1 | Statut |
|---|---|---|
| `-0.0` | les 64 bits IEEE sont l'identité : `-0.0` ≠ `0.0` ; `-0` entier → `0` (i64) | R9 muette → **choix L1**, testé (pandas `round_trip` préserve aussi le signe) |
| Grammaire des flottants | stricte, ASCII seulement : mantisse décimale (`1`, `1.5`, `.5`, `5.`) et exposant optionnel ; `nan`, `inf`, `infinity` (toute casse) et tout dépassement vers l'infini → `NON_FINITE` ; soulignés (`1_0`), espaces, hexadécimal, chiffres pleine largeur → `FLOAT_TEXT` | R9 dit « valeur de `float(texte)` » : `float()` accepte des formes que ni pandas ni R9 n'entendent → **précision L1** |
| Entier hors int64 | **refus** (`INT_RANGE`), jamais élargi en flottant, **y compris dans une colonne qui contient aussi des décimaux** (corrigé à la vérification finale) ; zéros de tête de toute longueur admis (retirés avant conversion) ; un entier DANS int64 reste arrondi par `float(texte)` dans une colonne décimale (R9, identique à pandas) | **plus strict que la lettre de R9 3.2** (« sinon `f64` »), qui ferait perdre de la précision en silence → **à amender dans R9** |
| Type d'une colonne | inféré du texte : toutes les cellules entières → `i64`, sinon `f64` ; `100` et `100.0` donnent deux kinds, donc deux empreintes | conforme à R9 3.2, testé |
| Dialecte CSV | UTF-8 sans BOM, RFC 4180 **strict** (`csv.reader(strict=True)`), LF ou CRLF (mélange admis), aucune ligne vide, aucun CR isolé, fin de ligne finale, cellule vide refusée | R9 3.2 + `strict` (plus strict) |
| Temps | seul `YYYY-MM-DD HH:MM:SS` naïf (ASCII) ; `T`, `Z`, décalage, fraction, date seule, `24:00`, `:60`, année 0 → `TIME_FORMAT` | conforme |
| Durée de barre | **déclarée** (entier positif, `bool` refusé) ; doit égaler le plus petit écart mesuré ; tous les écarts multiples ; trou aligné sur la grille admis | corrige le défaut D2 de la revue de R9 |
| Horodatage | strictement croissant ; écart non entier en secondes refusé ; au moins deux lignes pour les faits (l'empreinte seule admet une ligne) | R9 muette sur la ligne unique → **choix L1** |
| Noms de colonne | non vides, sans caractère de contrôle, encodables UTF-8 (substitut isolé refusé), uniques ; exactement une colonne `time` de kind `time_us` | R9 : noms « UTF-8 » → **précisions L1** |
| Fuseau | le module ne connaît que du naïf interprété UTC ; `time_semantics = "naive_utc_declared"` ; un texte en heure de Paris serait lu comme UTC et donnerait une autre empreinte **sans qu'aucun contrôle puisse le détecter** | **limite assumée** (hypothèse déclarée non prouvée, §23.3 F3) |

## 4. Parseur par défaut de pandas
Reproducteurs minimaux, figés sur pandas 3.0.3 : `25972.402815212394` → pandas par défaut lit `25972.402815212397`, `float()` et `round_trip` lisent la valeur exacte ; idem `13555.517785666361` → `…636` et `9789.474283095395` → `…396`. Sur 4 008 chaînes (4 000 décimales aléatoires à 10-17 chiffres + 8 cas fixes), mesure ponctuelle de la mission (graine 11, script jetable non conservé) : 561 divergences avec le défaut, 0 avec `round_trip` ; une autre série de 20 000 valeurs en avait donné 1 383 (≤ 15 chiffres significatifs) et 5 739 (17 chiffres) : l'ordre de grandeur, pas un chiffre normatif. Un test montre que le digest d'une trame lue avec le défaut **n'égale pas** celui des octets ; avec `round_trip` il l'égale (vecteurs R9, décimales difficiles, 12 trames aléatoires, 20 000 lignes). Le fichier réel n'a pas été parcouru (voir R9 section 3.4) ; `engine.load_data()` et les chargeurs historiques ne sont **pas** modifiés.

## 5. Tests (`tests/test_gate_v_frame_digest.py`)
Deux catégories, à ne pas confondre. **Tests à oracle indépendant** (valeurs attendues jamais calculées par le module) : littéraux des vecteurs R9 (V1-V3, recalculés par un programme indépendant) et oracle écrit dans le fichier avec d'autres primitives (`int.to_bytes`, `calendar.timegm`, `struct`, arrondi correct par `float(Fraction(...))`, signe lu dans le texte) ; ancrage : le test d'oracle vérifie d'abord que l'oracle égale les littéraux. **Tests de cohérence** (le module comparé à lui-même par deux chemins, ou à pandas) : digest des faits = digest autonome, formes textuelles équivalentes, parité pandas sur décimales difficiles et trames aléatoires ; ils détectent une dérive mais ne sont pas des oracles.

## 6. Performances (synthétique, Python 3.13.7, pandas 3.0.3, Windows 10, 8 CPU) — mesures, aucun seuil contractuel
| Lignes | CSV Mo | décodage s | digest s | faits s | S0 complet s | pandas `round_trip` s | pic Mo S0 | pic Mo digest |
|---|---|---|---|---|---|---|---|---|
| 100 | 0,01 | 0,0015 | 0,0002 | 0,0003 | 0,0020 | 0,0032 | 0,1 | 0,0 |
| 10 000 | 0,65 | 0,1742 | 0,0093 | 0,0197 | 0,1917 | 0,0523 | 8,0 | 0,2 |
| 100 000 | 6,48 | 1,6321 | 0,1400 | 0,2299 | 1,8724 | 0,4757 | 79,7 | 1,6 |
| 1 000 000 | 64,78 | 14,3604 | 1,4454 | 2,0117 | 15,9385 | 4,0189 | non mesuré | non mesuré |

Durée : médiane de 5 passes (1 passe à 1 000 000). Mémoire : pic `tracemalloc` des allocations Python, ≈ 800 octets/ligne (**le pic à 1 000 000 de lignes n'a pas été mesuré**). Le décodage stdlib est ≈ 3,5 à 4 fois plus lent que pandas : acceptable pour un recalcul côté auditeur, pas pour une boucle serrée.

## 7. Revue indépendante et vérification du delta
Relecteur neuf (agent `general-purpose`, lecture seule, 25 appels d'outil, ≈ 13 min 30 s) : **ACCEPT WITH FIXES**, aucun bloquant. Il a recalculé R9 3.2 depuis la prose seule (vecteurs V1-V3 égaux), mené un fuzz différentiel de 4 000 CSV contre une implémentation indépendante (2 976 trames distinctes acceptées : 0 écart, 0 collision de préimage) et ≈ 50 comparaisons avec pandas `round_trip` (aucun cas « module accepte, pandas diffère » ; tous les écarts vont vers le refus). Selon ce relecteur, les écarts L1 de la section 3 allaient tous vers le refus ; la revue du delta final a montré une exception (colonne mixte, voir ci-dessous), corrigée.

| Défaut | Sév. | Traitement | Preuve |
|---|---|---|---|
| D1 ReDoS quadratique dans la grammaire décimale (`[0-9]+\.?[0-9]*`) | MAJEUR | regex sans quantificateurs adjacents sur la même classe | reproduit (0,85 s à 4 000 chiffres, 3,1 s à 8 000) ; test RED (≈ 60 s à 40 000) puis < 1 s ; ancienne et nouvelle regex équivalentes sur 5 380 840 mots courts |
| D2 `ValueError` brute sur un entier de plus de 4 300 chiffres (colonne entièrement entière) | MAJEUR | refus typé `INT_RANGE` | test RED/GREEN (4 300, 4 301, 20 000 chiffres) ; zéros de tête admis |
| D3 `kind` non contrôlé par type (un `__eq__` piégé levait une erreur brute) | MINEUR | `type(kind) is str` exigé | test RED/GREEN |
| D4 `FrameRefused` non picklable ni copiable (workers) | MINEUR | `__reduce__` ; `detail` conservé | test RED/GREEN (pickle, copy, deepcopy) |
| D5 mutants survivants, vocabulaire non verrouillé, énoncés imprécis de la note | MINEUR | tests sous-types `float`/`int`/`FrameColumn`, DEL, 22 codes exacts ; énoncés de la section 5 et chiffres de la section 4 corrigés | mutation |
Mutation : **47/49** tués à ce stade ; les 2 survivants étaient des contrôles redondants avec `_validate_columns`. **Correction (vérification finale)** : ils n'étaient PAS strictement équivalents — un test différentiel sur 6 000 CSV hostiles ×2 mutants montre 0 entrée acceptée à tort mais 416 changements de **code** de refus (`NON_FINITE` ↔ `INT_RANGE`) quand deux colonnes sont défectueuses. La règle « le premier défaut dans l'ordre des colonnes est rapporté » est désormais verrouillée par un test : **49/49 tués, aucun survivant**. Vérification ciblée du delta **par l'auteur seulement** (pas de seconde relecture indépendante) : non relus par un tiers, les correctifs D1-D5 et les 9 tests ajoutés. Non vérifié : fichiers de plusieurs millions de lignes en mémoire, accès concurrents, `nasdaq_3m.csv` au-delà de la mission R9.

### 7 bis. Revue indépendante du delta final (seconde revue, limitée aux correctifs postérieurs à la première)
**ACCEPT WITH FIXES**, aucun bloquant. Confirmé : regex décimales équivalentes (300 000 mots aléatoires, 0 écart) et traitement linéaire sur des cellules de 131 000 caractères (9 formes hostiles, ≤ 20 ms), pickle/copy/deepcopy, ordre des défauts, stdlib seule, aucun fichier suivi modifié. Défauts : **(1) MAJEUR** — un entier hors int64 était élargi puis arrondi en `f64` dès qu'une cellule de la colonne était décimale (`99999999999999999999` avec `1.5` donnait `1e20`), ce que la note niait → **corrigé par TDD** (RED sur 4 cas, puis GREEN : l'entier hors int64 est refusé dans toute colonne) ; **(2) MINEUR** — zéros de tête refusés au-delà de 4 300 chiffres → corrigé (retrait des zéros avant conversion, 100 000 zéros testés) ; (3) ordre des défauts non testé sur colonnes explicites, (4) test de durée étroit → tests ajoutés (colonnes explicites, 5 formes hostiles) ; (5) décomptes de la note → harmonisés ; (6) formulation de la section 7 → corrigée. La vérification des correctifs (1)-(4) est **de l'auteur seulement** (pas de troisième relecture) ; mutation après correction : **52/52** tués. Les chiffres « mutants » et « mots testés » sont des mesures de l'auteur dont les scripts jetables ne sont pas conservés dans le dépôt.

## 8. Écart à R9 sur l'entier hors int64 — décision d'implémentation PROVISOIRE
R9 3.2 (texte actuel) : « toutes les cellules entières (`[+-]?[0-9]+`, dans l'intervalle int64) → `i64` ; sinon `f64` (valeur de `float(texte)`) ». Lue à la lettre, une colonne dont une cellule entière dépasse int64 devient `f64`, donc **arrondie** (au-delà de 2^53 la valeur change) : une identité de données silencieusement différente du texte. L1 **refuse** (`INT_RANGE`). Ce comportement est : **déterministe** (testé : 2^63, −2^63−1, 20 chiffres, plus de 4 300 chiffres, zéros de tête admis) ; **scientifiquement plus conservateur** (un refus ne peut jamais produire d'empreinte ni de fait, donc jamais de preuve) ; **compatible avec le périmètre autonome de L1** (aucun vecteur R9 V1-V3 n'est concerné ; aucun fichier valide au sens de R9 qui tient dans int64 n'est modifié). Ce n'est **pas** une adoption de R9 : c'est une divergence assumée, à régler avant L2.

**Amendement proposé de R9 3.2 (à traiter avant L2, seul)** — remplacer « …dans l'intervalle int64) → `i64` ; sinon `f64` » par : « …) → `i64` si **toutes** les cellules sont dans l'intervalle int64 ; **toute cellule entière hors int64 est refusée** (`INT_RANGE`), que la colonne soit entièrement entière ou qu'elle contienne aussi des décimaux, et n'est jamais élargie en `f64` ; une colonne contenant au moins une cellule non entière est `f64` (chaque cellule suivant la grammaire décimale stricte, un entier dans int64 y valant `float(texte)`) ; les zéros de tête n'affectent pas la valeur. » Cet amendement ne tranche aucune des décisions D1-D9.

## 9. Dépendances et suite
Dépend de : R9 (PROPOSED). Consommé plus tard par : L2 (schémas Coverage/Session/Seal), L3 (vérificateur), L6 (faits S0 côté auditeur). **Non fait ici** : D8 (B2), B3 v5, E3-A, B5, `RunSession`, `RunSeal`, orchestrateur V2, E3-J, chargeur V2 à lecture unique, correspondance `DataFrame` → colonnes de production (l'adaptateur n'existe que dans les tests).
