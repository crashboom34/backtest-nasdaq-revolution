# E3-E — K1 Étape 2 : contrat de preuve d'absence d'exposition des validations WF / MC / PS — PROPOSED (R9), NON NORMATIF, NON ACCEPTÉ, NON IMPLÉMENTÉ

**Statut (2026-10-24).** Gel de contrat de l'Étape 2 de K1. Il **remplace** `0025-proposal-E3E-Q2-STAGE2-DESIGN-PROPOSED.md` (conservé pour la traçabilité, bannière de renvoi ajoutée), qui contenait des défauts listés en section 1. L'Étape 1 (ADR 0025 §23.33, B3 v4) est ACCEPTED, IMPLEMENTED, TESTED, PUBLISHED et **n'est pas modifiée**. Rien ici n'est accepté, codé ni publié : aucun code de production, aucun commit, aucun push, aucun accès `FINAL_HOLDOUT`. `REAL` = DISABLED / NOT QUALIFIED · `GATE V` = NON PASSÉE · `FINAL_HOLDOUT` = NON ACCÉDÉ. Checkpoint : `HEAD` = `origin/master` = `7a8f1ad6328b30206d1c6f385f6be2a9b94b4d7a`.

**Verdict.** `K1 STAGE 2 CONTRACT READY FOR USER ACCEPTANCE` — au sens strict : contrat précis, exécuté en prototype de référence (hors production), relu par un relecteur indépendant (section 17), **soumis** à l'utilisateur. Ce n'est **pas** une garantie suffisante pour Gate V (section 12) et l'implémentation reste bloquée par l'absence d'orchestrateur V2 et d'E3-J (section 15).

**Avancement (2026-10-24).** Lot L1 publié (`gate_v_frame_digest.py`, commits 180078d et 96f3597). Lot L2 (modèles purs `RunDataCoverage` / `RunSession` / `RunSeal`, sections 5.1-5.3, `binding_kind = MARKET_DATA_FRAME` seulement) : implémenté, testé et soumis à audit final ; **acceptation utilisateur LIMITÉE aux clauses listées en section 5.6**. Les SHA de publication sont consignés dans le handoff (§74) et vérifiables par `git log`, pas dans ce texte. La couverture `DERIVED` (5.4), `evidence_hash` (5.5) et les décisions D1-D9 ne sont ni implémentés ni acceptés par L2 ; seul l'amendement A-3.2 (section 3.2) est intégré à ce texte. **R9 dans son ensemble reste PROPOSED, NON NORMATIF, NON ACCEPTÉ.**

**Preuves jointes.** Vecteurs littéraux : `0025-proposal-E3E-Q2-STAGE2-VECTORS.json` (recalculés par un second programme qui n'importe pas le premier). Prototype de référence (non production, scratchpad de la mission) : 52 cas RED/GREEN, 156 scénarios de crash, parité du digest avec pandas 3.0.3 (section 11).

---

## 1. Défauts de la proposition précédente corrigés par ce contrat

| # | Défaut constaté | Preuve | Correction |
|---|---|---|---|
| C-1 | `run_record_hash` défini comme « hash du JSON canonique » du run et « porté par `content_hash` ». Faux : le `content_hash` d'un finding est le SHA-256 des **octets bruts** du fichier (B2, `gate_v_exposure_scan.py:775`) ; `save_validation_run` écrit `json.dumps(..., indent=2)` non trié (`atomic_json_store.py:65`). | code | `run_record_sha256` = SHA-256 des octets exacts de `validation_run.json` (section 5). Aucun hash « canonique » du run. |
| C-2 | La preuve reposait sur `loaded_content_sha256 == hash(S0)`, c.-à-d. `SHA256(DataFrame) == SHA256(CSV)`. Impossible, et l'existant le reconnaît : « deux lectures disque indépendantes… pas une preuve atomique » (`job_store.py:464-475`). | code + docstring | Trois objets, trois empreintes, chaîne de provenance et lecture unique des octets (sections 2-3). |
| C-3 | « Couverture calculée sur le `df` passé » sans traiter le cas réel : le V1 appelle `load_market_data_fn()` puis choisit `resume` selon l'existence d'un checkpoint (`gate_v_campaign.py:1092-1093`) ; une reprise peut donc recevoir un autre `df`. | code | `RunSession` + règle R0 : une seule trame par run, vérifiée à chaque session avant tout calcul (sections 4, 6). |
| C-4 | Source non déclarée : `optimizer._worker_run_single` **recharge `config.data_file`** quand `_worker_df_global is None` (`optimizer.py:1236-1257`), et la capture V1 retire `data_file` du fingerprint (`walk_forward.py:2160`). | code | Contrainte C-DF : l'orchestrateur V2 neutralise `data_file` ; RED dédié (section 11). |
| C-5 | « Épinglage par le Manifest » : le Manifest V2 n'a que 17 clés strictes, sans hash de preuve (`gate_v_exposure_interpreters.py:208-212`). | code | Épinglage par la chaîne `inventory_id` (hash composite du finding) ; changement de Manifest = décision D2 (section 14). |
| C-6 | Amendements oubliés : B5 refuse toute `ABSENCE_ESTABLISHED` et limite le relevé aux seuls jobs/OOS (`gate_v_exposure_store.py:647`, `:678-679`, `:685-693`). | code | Liste complète des amendements (section 9). |
| C-7 | MC/PS non analysés par leurs lectures réelles : MC relit `walk_forward/folds/*/oos_trades.csv` (`gate_v_campaign.py:1225-1228`) ; PS relit les checkpoints `.gate_v_checkpoints_v1`, le `data_manifest_path` **externe** et le plan de split (`:1366-1370`). Aucun de ces fichiers n'est haché ni connu de B3 v4 (inconnus bloquants). | code | Table des dépendances effectives et contrat de dérivation (section 8). |
| C-8 | « F3 raffiné » (N20) n'est pas exprimable dans E3-A : `ChronologyFacts` ne porte que `s0_max_time_utc` (`gate_v_final_holdout_protocol.py:1149-1163`) ; l'étendre changerait la version des règles de classification. | code | Le même contrôle est fait dans B3 (`dernière clôture <= ws`) ; **F3 d'E3-A inchangé** ; résiduel nommé (section 12). |
| C-9 | Aucune règle « un run scellé est terminal ». Révélée par la simulation de crash : une reprise après le Seal créait une session non listée et rendait le run définitivement non prouvable. | simulation | Règle R0 (section 6). |
| C-10 | Parseur de flottants par défaut de pandas : diffère de `float()` sur 7 % de valeurs d'une série à 2-15 décimales (1383 sur 20 000, section 3.4) ; le digest recalculable en stdlib exige un parseur correctement arrondi. | mesure | `float_precision="round_trip"` dans le chargeur V2 (décision D3). |
| C-11 | Fuseau : la colonne `time` est naïve, interprétée UTC par convention (hypothèse **déclarée non prouvée**, §23.3 F3). Le contrat précédent ne disait pas ce que l'hypothèse engage. | ADR | Section 4.7 : l'hypothèse reste une déclaration humaine (F6) ; aucun durcissement caché ; décision D4. |
| C-12 | Défaut propre à ce travail (prototype) : le contrôle « même campagne » du parent utilisait un mauvais indice et ne se déclenchait jamais ; attrapé par RED R2-33 et corrigé. | exécution | Le test R2-33 est conservé dans la matrice. |

---

## 2. Trois objets distincts, trois empreintes

Aucune égalité n'est présumée entre eux ; le lien est une **chaîne de provenance** (section 3), vérifiable de bout en bout.

| Objet | Définition | Empreinte | Produite par | Vérifiée par | Ne prouve pas |
|---|---|---|---|---|---|
| **O1 — octets de S0** | fichier CSV immuable désigné par `dataset_snapshot_id = "local_csv:sha256:<h>"` | `source_sha256` = SHA-256 des octets exacts | identité existante (`market_data/content_hash.py`) | recalcul par l'auditeur (E3-J / attestation) | que le calcul a lu ces octets |
| **O2 — trame chargée** | table obtenue par le **chargeur V2** à partir des **mêmes octets lus une seule fois** | `frame_sha256` (digest de trame v1, 3.2) sur les **colonnes sources** | orchestrateur V2 (sur l'objet réellement transmis au calcul) **et** auditeur (recalcul stdlib depuis O1) | égalité O2(orchestrateur) = O2(auditeur) ; elle établit le lien O1→O2 | que les colonnes dérivées n'ont pas été altérées (fonctions de `time`, hors digest, 3.1) |
| **O3 — données accessibles au calcul** | ce que chargeur, optimiseur, moteur et stratégie *pouvaient* lire | **aucune empreinte propre** : bornée par O2 (trame entière, conservateur) | — | — | tout accès hors chemin de données (code de stratégie, consultation humaine : limite §23.30.1, inchangée) |

**O3 est borné par O2, pas par les dates des folds ni par la troncature du moteur.** Faits de code : `engine.run_backtest` tronque `df[time_paris < end]` avant `prepare()` (`engine.py:155-157`) ; `resolve_execution_window` fournit un contexte allant jusqu'à la dernière barre de la fenêtre (`optimizer.py:263`) ; mais le `df` complet est lu pour filtrer, `coverage_bars` relit `df["time_paris"]` en entier (`walk_forward.py:684-688`) et le repli de worker manipule des trames entières. La troncature est une **propriété du code**, pas un artefact lié au run : elle ne devient jamais une preuve d'exclusion (cohérent avec §23.30.1, qui refuse déjà `X` comme borne de `A`).

---

## 3. Chaîne de provenance O1 → O2

### 3.1 Chargeur V2 (`gate_v_s0_frame_loader_v1`, spécifié en code au lot L7)
1. **Une seule lecture** : `raw` = octets du fichier S0 ; `source_sha256 = SHA-256(raw)` ; `dataset_snapshot_id = "local_csv:sha256:" + source_sha256`. Plus de seconde lecture disque ; le contrôle `(taille, mtime)` n'est pas une garantie (`job_store.py:536`).
2. `df = pandas.read_csv(BytesIO(raw), parse_dates=["time"], float_precision="round_trip")` — **les mêmes octets**. Équivalent du chemin transparent `read_raw_validated_csv` (colonnes canoniques `time, open, high, low, close` exigées, aucune colonne ajoutée ni retirée).
3. Colonnes dérivées : `engine._add_market_time_columns(df)` inchangée. Elles ne participent pas au digest : ce sont des fonctions pures de `time` (et de la base `tzdata` pour `time_paris`) ; elles ne portent aucune valeur de marché supplémentaire.
4. `frame_sha256` et les faits de trame sont calculés sur `df` **avant** le premier appel de calcul, et recalculés **après** la session de calcul (comparaison, 4.6).
5. Un `FrameHandle` encapsule `df` ; l'orchestrateur ne passe au calcul que `handle.df`. Aucun autre `DataFrame`, aucun filtre, aucune transformation, aucun rééchantillonnage entre le chargeur et le calcul.

### 3.2 Digest de trame `gate_v_frame_digest_v1` — préimage exacte (recalculable en stdlib)
Entrée : colonnes **sources** dans l'ordre du fichier. Types admis : `time_us` (colonne `time` : microsecondes depuis 1970-01-01, entier signé), `i64`, `f64` (finis). Tout autre type, `NaN`, `inf`, nom en double, `time` absente ou non unique, ligne mal formée → **refus** (`FrameRefused`, aucune preuve).

```
H = SHA-256( b"gate_v_frame_digest_v1\n"
           + compact({"columns":[{"kind":..,"name":..},...],"row_count":N})   # clés triées, séparateurs (",",":"), ensure_ascii=False, UTF-8
           + b"\n"
           + pour chaque colonne, dans l'ordre :
               b"column:" + nom_UTF-8 + b"\n"
             + struct.pack(">Q", 8*N)                        # longueur d'octets de la colonne
             + N valeurs, chacune sur 8 octets big-endian    # ">q" pour time_us et i64, ">d" pour f64 )
```
Classification d'une colonne par le **texte** du fichier (reproductible hors pandas) : `time` → `time_us` (format exact `YYYY-MM-DD HH:MM:SS`, naïf) ; toutes les cellules entières (`[+-]?[0-9]+`, dans l'intervalle int64) → `i64` ; sinon `f64` (valeur de `float(texte)`, arrondi correct). Un autre format d'heure est **refusé** en v1 (pas de devinette).

**Amendement A-3.2 (2026-10-24, mission L2 ; limité à cette clause, D1-D9 inchangées).** Le « sinon `f64` » ci-dessus ne s'applique PAS à un entier hors int64 : (a) toute cellule entière (`[+-]?[0-9]+`) hors de l'intervalle int64 est **refusée** (`INT_RANGE`), que la colonne soit entièrement entière ou qu'elle contienne aussi des décimaux ; elle n'est jamais élargie en `f64` (appliqué à la lettre, « sinon `f64` » arrondirait un entier démesuré en silence, p. ex. `99999999999999999999` avec `1.5` donnerait `1e20`) ; (b) un entier DANS int64 reste converti par `float(texte)` dans une colonne décimale (arrondi correct, identique à pandas) ; (c) les zéros de tête n'affectent pas la valeur : ils sont retirés avant toute conversion, sans limite de longueur, et ne changent ni le kind ni le digest d'une valeur déjà dans int64. Cet amendement reprend la décision d'implémentation de L1 (note L1, section 8) ; il ne modifie aucun vecteur V1-V3 ni aucune identité publiée. **Statut : proposé par la mission L2 et appliqué par ce seul texte ; R9 dans son ensemble reste PROPOSED.**

**Dialecte CSV** : UTF-8 sans BOM, RFC 4180 (virgule, guillemets), en-tête obligatoire, fins de ligne LF ou CRLF, **aucune ligne vide**, aucun CR isolé, fin de ligne finale obligatoire ; sinon refus (pandas saute les lignes vides, `csv.reader` non : les deux lecteurs divergeraient). **Correspondance trame → kind côté orchestrateur** : `datetime64[*]` naïf → `time_us` (conversion en microsecondes refusée si une valeur n'est pas un multiple exact de 1 µs) ; `int64` → `i64` ; `float64` → `f64` ; tout autre `dtype` (`object`, `float32`, `bool`, datetime avec fuseau, valeur manquante) → refus. Le kind inféré du texte du fichier et celui de la trame doivent coïncider colonne par colonne ; sinon les digests diffèrent et la preuve est refusée.

### 3.3 Faits de trame
`row_count >= 2` ; `time` strictement croissante (aucun doublon) ; écarts entiers en secondes ; `bar_duration_seconds` = durée **déclarée** du timeframe (entier > 0, ex. 180 pour M3), qui doit être égale au plus petit écart positif **mesuré** ; tous les écarts sont multiples de cette durée (grille). Une durée seulement mesurée est refusée : des écarts de 60 s mêlés à des barres de 180 s donneraient 60 s et feraient exclure à tort une barre M3 à cheval sur `ws` (RED R2-41). La déclaration vient de la déclaration humaine du jeu de données (F6) et est identique dans la couverture et dans les faits S0 ; `first_open_utc`, `last_open_utc`, `last_close_utc_exclusive = last_open_utc + bar_duration_seconds`. Instants : `YYYY-MM-DDTHH:MM:SS.ffffffZ`. La durée de la dernière barre est **toujours ajoutée** (ferme la question ouverte de §23.30.5).

### 3.4 Pourquoi `round_trip`
Mesure (prototype, 20 000 valeurs) : le parseur par défaut de pandas diffère de `float()` sur **1383** valeurs à ≤ 15 chiffres significatifs et sur **5739** à 17 chiffres ; `round_trip` : **0** écart. Sur les 30 000 premières lignes du CSV réel (2017-10 à 2018-02, hors holdout), les colonnes flottantes sont identiques dans les deux modes (prix à 2 décimales) ; l'égalité sur le fichier complet n'est **pas** présumée : elle est exigée par la comparaison des digests (sinon refus). Le lot L1 contient un test de parité pandas ↔ stdlib.

### 3.5 Faits S0 recalculés par l'auditeur (`S0FrameFacts`)
L'auditeur (E3-J / attestation, **pas** B3) relit les octets de S0, recalcule en stdlib `{source_sha256, source_size_bytes, dataset_snapshot_id, frame}` (mêmes fonctions que 3.2-3.3, la durée de barre déclarée étant un argument obligatoire) et les fournit à B3 comme argument typé. `s0_frame_facts_sha256` = SHA-256 des octets normatifs de cet objet ; il est consigné dans l'A0 (bloc informatif) et, quand N20 sera accepté, épinglé par l'attestation. Sans `S0FrameFacts` : aucune exclusion possible (comportement de l'Étape 1).

---

## 4. Géométrie de la couverture

### 4.1 Décision
**Un `RunDataCoverage` par run** (écriture unique, avant tout calcul), **un `RunSession` par session d'exécution** (création exclusive avant le calcul de la session), **un `RunSeal` par run** (après l'écriture du `ValidationRun`). Ni un enregistrement par invocation, ni un ensemble par fold.

### 4.2 Alternatives examinées
| Option | Verdict | Raison |
|---|---|---|
| Un enregistrement par invocation (TRAIN / TEST de chaque fold) | rejetée | 2 × (nombre de folds) enregistrements sans gain : toutes les invocations d'une session reçoivent le **même** objet `df` (`walk_forward.py:547-558`, `:643-647`, `:1034-1039`) ; la substitution inter-session (reprise) est le vrai risque, couvert par les sessions. |
| Un ensemble par fold | rejetée | idem ; de plus les checkpoints V1 (`walk-forward-capture-v1`) ne portent aucune *couverture* (le manifeste de checkpoint embarque l'identité `data_manifest.snapshot_id` / `content_hash` lue dans un fichier séparé, `walk_forward.py:1103-1110`, pas la trame) et ne doivent pas être modifiés (rétrocompatibilité). |
| Agrégation vérifiable de toutes les invocations | **retenue sous la forme** couverture unique + sessions + Seal | l'agrégation est la conjonction : « chaque session a vérifié `frame_sha256` == couverture » + « le Seal liste toutes les sessions et toutes les sorties ». |
| Couverture bornée par `effective_test_end` / troncature moteur | rejetée | propriété du code, non liée au run (section 2) ; rendrait l'exclusion dépendante de dates que `X` ne garantit pas. |
| Sous-trame (préfixe, filtre, rééchantillonnage) du fichier S0 | **hors périmètre v1** | exigerait un engagement par ligne (Merkle) ; toute trame ≠ S0 complet ⇒ non établi (section 7). |

### 4.3 Invariants de couverture
- **I-C1** La couverture est écrite **une seule fois** avant tout calcul, sans référence au run (acyclique).
- **I-C2** `trame consommée == trame de S0 entière` (mêmes colonnes sources, même ordre, mêmes lignes) ; sinon pas d'exclusion.
- **I-C3** `A_run = [first_open_utc, last_close_utc_exclusive)` de la **trame entière** ; demi-ouvert.
- **I-C4** Toute session vérifie `frame_sha256` de sa trame contre la couverture **avant** le premier calcul ; différent ⇒ `BINDING_CONFLICT`, aucune écriture, aucun calcul.
- **I-C5** `session_index` consécutifs `1..n` ; le Seal les liste tous ; une session non listée, manquante ou altérée ⇒ non établi.
- **I-C6** Toutes les sorties de calcul (`walk_forward/**`, y compris `.gate_v_checkpoints_v1/**`) sont listées dans le Seal avec leur SHA-256 et leur taille ; tout fichier non listé sous cette racine ⇒ non établi.
- **I-C7** P1 (`X_k ∩ W ≠ ∅` pour un fold) **établit** l'exposition ; il n'exclut jamais. Évaluation **fold par fold**, jamais sur l'enveloppe.
- **I-C8** Bornes demi-ouvertes ; durée de la dernière barre ajoutée ; instants UTC ; un fold à borne naïve ⇒ `TIMEZONE_UNKNOWN`, aucune preuve ne le neutralise.
- **I-C9** Couverture absente, illisible, invalide ou non attribuable ⇒ `UNRESOLVED`, jamais `FRESH`.

### 4.4 Couverture de chaque site d'appel
| Site | Données reçues | Couverture |
|---|---|---|
| `run_fold_train` → `Optimizer(df)` → `resolve_execution_window` | `df` de la session | trame entière (I-C3) |
| `_run_fold_test_core` → `_run_single` → `run_backtest` | idem | idem |
| `RESUME_ACTION_REPLAY_TEST` / `REDO` / `train_progress.csv` | `df` de la **nouvelle** session | I-C4 ; les candidats rechargés viennent de sessions antérieures déjà liées par leurs `RunSession` |
| `RESUME_ACTION_SKIP` / checkpoint V1 rechargé | aucune donnée de marché | résultat d'une session antérieure listée au Seal |
| `_worker_run_single` avec `_worker_df_global` | `df` transmis par `initargs` | idem |
| `_worker_run_single` **sans** initializer | **recharge `config.data_file`** | **source non déclarée** : contrainte C-DF — `data_file` neutralisé (chaîne vide) dans le `base_config` passé au calcul ; un test échoue si ce repli peut charger quoi que ce soit |
| `coverage_bars` | lit `time_paris` entier | aucune valeur de marché ; couvert par I-C3 |
| Code de stratégie (`strategies/*.py`) | `df` du moteur | aucune lecture de fichier constatée (recherche : aucun `open/read_*` dans `strategies/`, `scoring.py`, `monte_carlo.py`, `parameter_stability.py`, ni dans `engine.py` hors les chargeurs `load_data*`, appelés avant le calcul) ; **limite §23.30.1 inchangée** pour tout code futur |

### 4.5 Reprises
Un run peut s'étendre sur plusieurs sessions sans perdre la preuve **si** chaque session est liée. Un run dont une session est manquante, ou dont la trame a changé, n'est **jamais** réparé (section 6).

### 4.6 Mutation en place
Une stratégie pourrait modifier en place des tableaux partagés (`prepare()` opère sur `df.copy(deep=False)`). Garde : le Seal porte `frame_sha256_after` (digest recalculé après la session qui a calculé) ; pandas 3.0.3 (version du `.venv`) est en copy-on-write par défaut. `frame_sha256_after` est `null` **si et seulement si** le Seal est une récupération (aucun calcul dans cette session) : un Seal de session de calcul sans digest « après », ou une récupération qui en porte un, est refusé (RED R2-39, R2-40). Risque résiduel R-mut pour une session crashée (section 16).

### 4.7 Fuseau et calendrier
`time` est naïve, **interprétée UTC par convention** (`engine._add_market_time_columns`, contrat §23.3 F3, hypothèse déclarée non prouvée). Ce contrat ne la prouve pas et ne la durcit pas en silence : la couverture exprime des instants UTC **sous cette hypothèse**, consignée `time_semantics = "naive_utc_declared"`. Les colonnes `time_paris` / `date_p` / `h_p` ne servent **jamais** à la couverture ; les ambiguïtés d'heure d'été (bornes de fold exprimées en heure de Paris) n'affectent que `X` (P1, sens qui durcit) et une borne naïve est refusée. Marge de sécurité éventuelle : décision D4.

---

## 5. Schémas et préimages exacts

Tous les enregistrements : **JSON normatif** (`serialize_normative_json`, §23.29.4 : clés triées, `indent=2`, LF final, UTF-8, `allow_nan=False`, **aucun flottant**). Chaque hash d'artefact = **SHA-256 des octets exacts publiés**. Instants : `YYYY-MM-DDTHH:MM:SS.ffffffZ`. Emplacement : `validations/<validation_run_id>/`.

### 5.1 `run_data_coverage.json` — `MARKET_DATA_FRAME` (WF)
`coverage_semantics_version = "gate_v_run_data_coverage_v1"` · `binding_kind = "MARKET_DATA_FRAME"` · `validation_run_id` (== nom du dossier) · `dataset_snapshot_id` (== `"local_csv:sha256:" + source_sha256`) · `source_sha256` · `source_size_bytes` · `loader_id = "gate_v_s0_frame_loader_v1"` · `frame` (exactement : `frame_digest_version`, `frame_sha256`, `row_count`, `columns[{name,kind}]`, `bar_duration_seconds`, `first_open_utc`, `last_open_utc`, `last_close_utc_exclusive`, `time_semantics`) · `runtime` (`python`, `pandas`, `numpy` : **informatif**, ignoré par le verdict et par la comparaison de récupération). **9 clés exactes.**

### 5.2 `run_session_NNNN.json` (`NNNN` = `session_index` sur 4 chiffres, à partir de `0001`)
`session_semantics_version = "gate_v_run_session_v1"` · `validation_run_id` · `coverage_sha256` (octets de `run_data_coverage.json`) · `session_index` · `frame_sha256_before` (trame de CETTE session, == couverture) · `frame_row_count` · `resumed` (booléen : un manifeste de checkpoint préexistait). **7 clés exactes.** Création **exclusive** avant tout calcul de la session ; un seul écrivain par campagne.

### 5.3 `run_seal.json`
`seal_semantics_version = "gate_v_run_seal_v1"` · `validation_run_id` · `validation_type` ∈ {`walk_forward`, `monte_carlo`, `parameter_stability`} · `run_record_sha256` (octets de `validation_run.json`) · `coverage_sha256` · `sessions[{session_index, session_sha256}]` (WF : au moins une, indices `1..n` ; dérivés : liste vide) · `output_artifacts[{path, sha256, size}]` triés par `path` (WF : tout `walk_forward/**` ; dérivés : liste vide) · `frame_sha256_after` (hex ou `null`) · `finalized_by_recovery` (booléen). **9 clés exactes.** Déterministe (aucun horodatage). Règle WF : `frame_sha256_after` est `null` ⇔ `finalized_by_recovery` est vrai ; sinon il égale `frame_sha256` de la couverture. Dérivés : `null`.

### 5.4 `run_data_coverage.json` — `DERIVED` (MC / PS)
`coverage_semantics_version` · `binding_kind = "DERIVED"` · `validation_run_id` · `validation_type` ∈ {`monte_carlo`, `parameter_stability`} · `parent_validation_run_id` (un WF de la **même** campagne, jamais un dérivé) · `parent_run_record_sha256` · `parent_seal_sha256` · `inputs[{role, path, origin, sha256, size}]` triés par `path`. **8 clés exactes.** **Aucune fenêtre n'y figure.**
`origin` ∈ {`PARENT_SEALED_OUTPUT` (le chemin doit figurer dans le Seal du parent avec le même hash), `SIBLING_RUN` (`validation_run.json` d'un run de la campagne), `DECLARATION_FILE` (fichier sans valeur de marché ; `path = "plan.json"` relu, ou `"external:<role>"` épinglé par hash seulement)}.
**Table fermée rôle → (origine, chemin exact)** — toute autre combinaison est refusée (`INPUT_INVALID`), tout rôle inconnu aussi, tout doublon de chemin aussi ; la `size` épinglée est vérifiée contre les octets (ou contre le Seal du parent) :

| Rôle | Origine | Chemin |
|---|---|---|
| `parent_validation_run` | `SIBLING_RUN` | `validations/<parent>/validation_run.json` |
| `sibling_monte_carlo_run` (PS) | `SIBLING_RUN` | `validations/gate_v_v2_<campagne>_monte_carlo/validation_run.json` |
| `campaign_plan` | `DECLARATION_FILE` | `plan.json` (relu) |
| `split_plan` (MC et PS) | `DECLARATION_FILE` | `external:split_plan` (épinglé par hash) |
| `data_manifest` (PS) | `DECLARATION_FILE` | `external:data_manifest` (épinglé par hash) |
| `oos_trades:NNN` (MC, un par fold) | `PARENT_SEALED_OUTPUT` | `walk_forward/folds/fold_NNN/oos_trades.csv` |
| `capture_manifest` (PS) | `PARENT_SEALED_OUTPUT` | `walk_forward/.gate_v_checkpoints_v1/manifest.json` |
| `capture_fold:NNN` (PS, un par fold) | `PARENT_SEALED_OUTPUT` | `walk_forward/.gate_v_checkpoints_v1/folds/fold_NNN.json` |

L'ensemble des rôles doit égaler exactement l'ensemble attendu (MC : `parent_validation_run`, `campaign_plan`, `split_plan`, `oos_trades:*` ; PS : `parent_validation_run`, `sibling_monte_carlo_run`, `campaign_plan`, `split_plan`, `data_manifest`, `capture_manifest`, `capture_fold:*`). Le run dérivé a `validation_type` égal à celui de la couverture et du Seal (∈ {`monte_carlo`, `parameter_stability`}) et le **même** `dataset_snapshot_id` que son parent. Le `manifest.json` de campagne n'est **pas** une entrée : c'est un état d'orchestration mutable (schéma strict vérifié par B3 v4), sans valeur de marché, relu et réécrit à chaque phase (8.1).

### 5.5 Hash composite d'un finding (`evidence_hash`)
`evidence_hash = SHA-256( compact({"coverage": sha(coverage), "run": sha(run), "s0_facts": s0_frame_facts_sha256 | null, "seal": sha(seal) | null}) )`, où `s0_frame_facts_sha256` = SHA-256 des octets normatifs de l'objet `S0FrameFacts` fourni à B3 (`null` s'il n'est pas fourni). Il devient le `content_hash` du finding **dès que le dossier du run contient une couverture, quel que soit le verdict** (exposition, absence, non résolu) ; sans couverture (ancien run) le `content_hash` reste le hash des octets du run (continuité des identités v4). Raison : `inventory_id` couvre le `content_hash` de chaque finding ; le composite lie donc run, couverture, sceau **et faits S0 fournis** à l'identité de l'inventaire sans modifier E3-A — un appelant qui fournirait d'autres faits obtiendrait un autre `inventory_id` (RED R2-47). Limite : `static_sources_digest` exclut les findings `NO_OVERLAP` (`gate_v_final_holdout_protocol.py:1130`) ; une altération du run, de la couverture ou du sceau après une `RESERVATION` change donc `inventory_id` mais **pas** ce digest, et n'est détectée qu'à l'attestation, à l'`ADMISSION` ou à l'étape 13 (comparaison d'`inventory_id`), pas à l'étape 8 de la `RESERVATION` (qui ne compare que le digest). Conséquence assumée, à consigner dans 23.34.

### 5.6 Clauses acceptées par l'utilisateur pour le lot L2 (2026-10-24) — acceptation LIMITÉE, R9 reste PROPOSED dans son ensemble
**Acceptées, pour les seuls modèles purs L2 :** (1) 5.1 `RunDataCoverage` avec `binding_kind = MARKET_DATA_FRAME` ; (2) 5.2 `RunSession` ; (3) 5.3 `RunSeal` (structure ; vérification croisée walk-forward) ; (4) la géométrie D1 **limitée à ces trois modèles** (une couverture par run, une session par session, un sceau par run) ; (5) les références et hashs internes nécessaires, **sans** épinglage opérationnel D2 ; (6) les invariants **purs** de digest avant/après de D7 (aucun contrôle runtime des workers) ; (7) l'amendement A-3.2 (section 3.2) ; (8) la règle R0 « un run scellé est terminal » **dans la machine d'états pure seulement**. **Adaptations acceptées** : aucune clé `sessions` dans la couverture (le rattachement des sessions est vérifié par `verify_run_evidence`, car une liste de sessions dans la couverture créerait un cycle de hash) ; digest « après » dans le Seal, jamais dans la Session ; aucun « rôle » de session inventé ; `FRAME_BEFORE_MISMATCH` à l'ouverture d'une session tient lieu du conflit de trame de I-C4 (`BINDING_CONFLICT` est réservé à une seconde couverture sémantiquement différente).
**NON acceptées (restent PROPOSED ou hors périmètre) :** D1-D9 dans leur ensemble ; D8 (amendement B2) ; la couverture `DERIVED` et sa table de rôles (5.4) ; `evidence_hash` (5.5) ; la séquence de publication E3-C et la matrice de crash du monde réel (6.2-6.3) ; le verdict d'un run WF (section 7), B3 v5, les deux SourceKind additifs, B5, l'orchestrateur V2, E3-J ; toute preuve d'exclusion de bout en bout. L2 ne produit ni verdict `FRESH` / `NO_OVERLAP` / admission / Claim, ni objet d'autorisation.

---

## 6. Chronologie, graphe acyclique, publication, crashs

### 6.1 Graphe de dépendances (aucun cycle)
```
O1 octets S0 ─(lecture unique)─► O2 trame ─► frame_sha256
                                              │
        RunDataCoverage  ◄────────────────────┘      (écrite UNE fois, ne référence ni run ni seal)
              │
        RunSession_k  (référence coverage_sha256) ──► calcul de la session k ──► sorties walk_forward/** + checkpoints
                                                                     │
        ValidationRun (completed_at fixé ici) ◄──────────────────────┘      (aucun champ de couverture : schéma historique inchangé)
              │
        RunSeal  (référence run_record_sha256, coverage_sha256, sessions, sorties)
              │
        finding.content_hash = evidence_hash(run, coverage, seal) ──► inventory_id / A0 ──► attestation, RESERVATION, ADMISSION (E3-J)
        Dérivés : Coverage(DERIVED) référence parent_seal_sha256 ──► run dérivé ──► Seal dérivé   (le parent précède toujours)
```
L'ordre est un ordre de **dépendance de hash**, pas d'horloge : aucun nœud n'est référencé par un ancêtre.

### 6.2 Séquence de publication d'un WF
**Précondition PC-1 : un seul écrivain par campagne** (verrou de campagne déjà existant côté D4, hypothèse déjà posée par E3-C). `T0` créer le répertoire du run puis rendre son parent durable (barrière de lecture, précondition de l'appelant d'E3-C) → `T1` publier `run_data_coverage.json` (création exclusive, E3-C `publish_json_by_link`) → `T2` publier `run_session_NNNN.json` → calcul de la session → persistance des sorties (V1 : `persist_walk_forward_run`) → `T3` écrire `validation_run.json` avec `save_validation_run` → `T4` publier `run_seal.json`.
- **`T3` n'est pas exclusif** : `save_validation_run` passe par `save_atomic` (`is_file()` puis `os.replace`, `atomic_json_store.py:57-66`) — un remplacement concurrent est possible entre le test et l'`os.replace`. L'exclusivité repose sur PC-1 ; un run remplacé *avant* le Seal serait scellé tel quel (risque R-concurrence, section 16). Le run contient des flottants : il ne peut pas passer par `publish_json_by_link` (JSON normatif sans flottant), contrairement à la couverture, aux sessions et au Seal.
- **R0 — un run scellé est terminal** : si `run_seal.json` existe, l'orchestrateur ne crée **aucune** session, sortie ni run, et ne charge **aucune** donnée de marché ; si l'appelant fournit une trame, elle est comparée à la couverture (≠ ⇒ `BINDING_CONFLICT`).
- **Entrée d'une session de calcul** : recalcul de `frame_sha256` ; couverture existante ⇒ comparer **sémantiquement** (tous les champs sauf `runtime`) ; différent ⇒ `BINDING_CONFLICT` (rien n'est écrit, rien n'est remplacé).
- **Reprise sans chargement de données** (V1 : `aggregate.json` présent, aucun run — `gate_v_campaign.py:1087-1090`) : aucune trame n'est chargée, **aucune session n'est créée** ; le run est construit depuis des sorties déjà persistées par des sessions antérieures listées ; le Seal est alors une récupération.
- **Récupération après `T3`, avant `T4`** : le run existe ; le Seal est reconstruit depuis des artefacts **durables** (couverture, sessions listées, octets du run, sorties), avec `finalized_by_recovery = true` et `frame_sha256_after = null` ; ce Seal est déterministe. Aucun recalcul, aucun nouveau run.
- **Collision** : toute création exclusive qui échoue (`FileExistsError` / `SlotOccupiedError`) n'est acceptée comme idempotente que si les octets existants sont **identiques** (couverture, Seal) ; une session ne se rejoue jamais ; tout autre cas ⇒ refus, l'existant **fait foi** et n'est jamais écrasé, supprimé ni « réparé ».
- **E3-C** : une publication `PUBLISHED_UNCONFIRMED` (y compris `LINK_OUTCOME_UNKNOWN`) rend le slot **binding** : l'orchestrateur re-confirme (`confirm_published_slot`) ou s'arrête pour décision humaine, il ne republie jamais. Sous Windows le profil est `SIMULATED_DURABLE` (aucune valeur de preuve de durabilité, ADR 23.2) ; seul `POSIX_DIR_FSYNC` vaut pour `REAL`.
- **Orphelins de publication** : un kill laisse `<nom>.<uuid32>.tmp` (`save_atomic`) ou `.exposure.tmp.<hex32>` (E3-C). B2 les rend aujourd'hui **inconnus et bloquants**, sauf le motif `EXPOSURE` sous `exposure/` (`gate_v_exposure_scan.py:398-399`) : sans amendement, un crash à `T3` ou pendant `persist_walk_forward_run` rendrait le run non prouvable à vie. Amendement B2 requis (section 9, décision D8) : les orphelins de ces deux motifs, **dans le dossier du run et sous `walk_forward/**` seulement**, sont consignés (jamais lus, jamais comptés comme sorties), n'empêchent pas la preuve et ne sont jamais supprimés.
- **Dérivés (MC / PS)** : ordre **lire → épingler → calculer** : (1) l'orchestrateur lit ses entrées via un `PinnedReader` qui renvoie les octets et journalise chemin, SHA-256 et taille de ces mêmes octets ; (2) il publie `Coverage(DERIVED)` dont `inputs` est **généré** par ce journal (jamais saisi) — après vérification du Seal du parent ; (3) le lecteur est fermé, le calcul pur s'exécute sur les seuls octets déjà lus ; (4) run, (5) Seal. Toute ouverture de fichier après (3) fait échouer la phase. La couverture précède donc le *calcul*, pas les *lectures*. Fenêtre du journal : de (1) à (3) ; les relectures post-sauvegarde du run pour dériver le statut du Manifest (`_load_manifest_proofs`) sont hors fenêtre : elles ne lisent que ce que l'orchestrateur vient d'écrire et que le Seal couvre.

### 6.3 Matrice de crash (exécutée en simulation avec création exclusive réelle)
| Crash après | État observable | Verdict (aucune écriture de réparation) | Reprise |
|---|---|---|---|
| `T1` | couverture seule | `UNRESOLVED` (`NO_SEAL`) | recommence à `T2` après comparaison sémantique |
| `T2` (session *k*) | couverture + sessions | `UNRESOLVED` | nouvelle session *k+1* ; la session *k* reste listée |
| mi-calcul / mi-sorties | + sorties partielles | `UNRESOLVED` (`OUTPUT_UNSEALED` / `NO_SEAL`) | reprise V1 (checkpoints) ; sorties identiques acceptées, différentes refusées |
| `T3` | run écrit, pas de Seal | `UNRESOLVED` (`NO_SEAL`) | Seal par récupération (`finalized_by_recovery = true`) |
| `save_atomic` interrompu (orphelin `.tmp`) | orphelin + état précédent | selon l'état (jamais `NO_OVERLAP` avant le Seal) ; orphelin consigné si D8 est accepté | reprise normale ; l'orphelin n'est jamais supprimé |
| reprise sans chargement de données (`aggregate.json` sans run) | sorties complètes, pas de run | `UNRESOLVED` | run construit depuis les sorties, Seal par récupération, aucune session créée |
| `T4` | complet | `ABSENCE_ESTABLISHED` | R0 : rien à faire |
| après `T4`, reprise lancée | complet | inchangé | R0 : **aucune** session créée |

Résultat de la simulation (le chemin « sans chargement » et les orphelins sont couverts par la matrice 11, pas par la simulation de crash) : **156 scénarios** (crash en chaque transition × second crash éventuel en chaque transition × reprise) : 0 échec ; **0** état partiel classé « absence établie » ; couverture inchangée dans tous les cas ; un seul Seal ; collision de couverture (trame différente) ⇒ `BINDING_CONFLICT` sans modification ; collision de session ⇒ `FileExistsError`.

### 6.4 Garde D5 (additive, hors Manifest)
`assert_gate_v_pre_holdout_evidence_complete` (D5) gagne une vérification **additive** : pour chaque run référencé, `run_seal.json` présent et cohérent (hash du run, de la couverture). Aucun champ du Manifest n'est ajouté (décision D2 pour l'alternative).

---

## 7. Verdict d'un run WF (B3 v5)

Entrée supplémentaire de `interpret_audit_roots` : `s0_frame_facts: Optional[S0FrameFacts]` (défaut `None` ⇒ comportement identique à la v4). Ordre des étapes (calqué sur §23.30.1) :

1. Anomalie de lecture, schéma de run invalide, fold à borne invalide ou naïve ⇒ `UNRESOLVED` (`INVALID_SCHEMA` / `TIMEZONE_UNKNOWN`). **Aucune preuve ne le neutralise.**
2. **P1 par fold** : un `X_k = [train_start_k, effective_test_end_k)` recoupe `W` ⇒ `RESOLVED` / `OVERLAPS`, preuve `ESTABLISHED_BY_EXECUTION_WINDOW`, fenêtre = enveloppe des `X_k` recoupants.
3. **P2′** : couverture valide et attribuable, `[first_open, last_close_exclusive) ∩ W ≠ ∅` ⇒ `RESOLVED` / `OVERLAPS`, preuve `ESTABLISHED_BY_LOADED_COVERAGE` (le relevé cite la couverture, comme P2 cite le manifeste de job).
4. **Exclusion** — conjonction de **toutes** les conditions : `S0FrameFacts` fourni ; `coverage.source_sha256` et taille == faits S0 ; `coverage.frame` == `S0FrameFacts.frame` (digest, lignes, colonnes, barre, bornes) ; `run.dataset_snapshot_id` == `coverage.dataset_snapshot_id` ; `last_close_utc_exclusive <= ws` ; Seal présent, de version connue, attribuable, `run_record_sha256` et `coverage_sha256` égaux aux octets lus ; sessions `1..n` toutes présentes, hash égaux, `frame_sha256_before` == couverture, aucune session non listée ; `frame_sha256_after` nul ⇔ récupération, sinon égal ; durée de barre déclarée égale (couverture, faits S0) ; `output_artifacts` == contenu exact de `walk_forward/**` (orphelins de publication exclus) ; aucun fichier inconnu dans le dossier du run (orphelins exclus) ⇒ `RESOLVED` / `NO_OVERLAP`, preuve `ABSENCE_ESTABLISHED`, fenêtre `A_run`, `content_hash = evidence_hash`.
5. Sinon ⇒ `UNRESOLVED` (`WINDOW_UNKNOWN`), preuve `ABSENCE_NOT_ESTABLISHED`, avec la liste fermée des motifs de refus (informative, hors identité) : `NO_COVERAGE`, `COVERAGE_INVALID`, `COVERAGE_NOT_ATTRIBUTABLE`, `LOADER_UNKNOWN`, `NO_S0_FACTS`, `S0_MISMATCH`, `FRAME_MISMATCH`, `RUN_SNAPSHOT_MISMATCH`, `CLOSE_AFTER_WS`, `NO_SEAL`, `SEAL_INVALID`, `SEAL_NOT_ATTRIBUTABLE`, `RUN_ALTERED`, `COVERAGE_ALTERED`, `FRAME_MUTATED`, `FRAME_AFTER_MISSING`, `FRAME_AFTER_UNEXPECTED`, `DERIVED_SNAPSHOT_MISMATCH`, `PARENT_*`, `INPUT_*`, `SESSION_MISSING|GAP|ALTERED|FRAME_MISMATCH|UNLISTED`, `OUTPUT_MISSING|UNSEALED|ALTERED`, `UNKNOWN_RUN_FILE`.

Un run **sans couverture** (tout run produit avant l'Étape 2) reste `UNKNOWN_SOURCE` / `WINDOW_UNKNOWN` comme en v4 : non établi, jamais `FRESH`. Aucun `ValidationRun` historique n'est réécrit.

---

## 8. MC et Parameter Stability

### 8.1 Dépendances effectives (lectures de l'orchestrateur, pas seulement imports)
| Phase | Lectures réelles (V1 `gate_v_campaign.py`) | Traitement |
|---|---|---|
| Entrée de toute phase (`execute_gate_v_campaign`) | `plan.json` · **plan de split** `plan.split_plan_path` (`:1551`, externe) · `manifest.json` de campagne (`:1568`, mutable, réécrit à chaque phase) | `plan.json` et plan de split : rôles `campaign_plan` / `split_plan` ; `manifest.json` : **exempté** (état d'orchestration, schéma strict B3, aucune valeur de marché) |
| MC | `validations/<WF>/validation_run.json` (`load_validation_run`) · `walk_forward/folds/<id>/oos_trades.csv` × N folds (`:1225-1228`) · `base_config` en mémoire (capital initial) | `parent_validation_run`, `oos_trades:NNN` |
| PS (par fold) | `walk_forward/.gate_v_checkpoints_v1/manifest.json` et `folds/<id>.json` × N (`load_walk_forward_captured_run_v1`, `:1366`) · **`data_manifest_path` (externe)** (empreinte de reprise, `:1368`) · `validation_run.json` du WF et du MC | `capture_manifest`, `capture_fold:NNN`, `data_manifest`, `parent_validation_run`, `sibling_monte_carlo_run` |
| Après sauvegarde (`_load_manifest_proofs`, `:1306`, `:1445`) | relecture des runs qui viennent d'être écrits, pour dériver le statut | hors fenêtre du journal (6.2) ; couvert par le Seal |

Les modules `monte_carlo.py` et `parameter_stability.py` n'ont aucun accès fichier (recherche statique ; test AST R-Q2-13 conservé). Le marché n'est **jamais** lu par MC ni PS.

### 8.2 Contrat de dérivation DC-1 (renforcé)
Une preuve dérivée n'est recevable que si **toutes** les conditions tiennent :
1. le parent est un WF de la **même** campagne, ni un dérivé, ni lui-même, **unique** (pas de chaîne, pas de cycle) ;
2. le parent est vérifié (Seal valide) et `parent_run_record_sha256` / `parent_seal_sha256` égalent les octets lus ;
3. l'ensemble des entrées est **exhaustif** pour le type (table fermée de 5.4) et provient du journal de lecture ; chaque entrée est épinglée par SHA-256 et taille, à l'origine et au chemin imposés par son rôle ;
4. toute entrée `PARENT_SEALED_OUTPUT` figure dans le Seal du parent avec le même hash (le dérivé ne peut lire qu'un artefact que le parent a scellé) ;
5. toute entrée `DECLARATION_FILE` appartient à une classe sans valeur de marché (plan de campagne, plan de split, `BacktestManifest`) ; les fichiers externes sont épinglés par hash, jamais relus par le scanner (E3-J les re-hache à chaque vérification : obligation O-J3) ;
6. les modules de calcul sont des feuilles (test AST) ;
7. le dérivé **ne porte aucune fenêtre** : le verdict est recalculé depuis le Seal du **parent**. Parent exposé (`OVERLAPS`) ⇒ dérivé `OVERLAPS` (fenêtre recalculée = celle du parent, jamais saisie) ; parent non établi ⇒ dérivé non établi ; parent à absence établie et conditions 1-6 ⇒ dérivé `NO_OVERLAP` (fenêtre = `A_run` du parent, par DC-1 : `exposition(dérivé) ⊆ exposition(parent)`).

Parent absent, altéré, en double, cyclique, d'une autre campagne, entrée altérée, non scellée ou hors ensemble ⇒ non établi.

---

## 9. Versions et rétrocompatibilité

| Élément | Changement | Identités / digests historiques |
|---|---|---|
| **E3-A `SourceKind`** | +2 membres exposants : `VALIDATION_RUN_PRE_HOLDOUT` (WF), `VALIDATION_RUN_DERIVED` (MC, PS) ; valeurs nouvelles seulement. Test publié `test_source_kind_has_twelve_values_split_8_2_2` à amender (8 → 10 exposants, 2, 2). | `EXPOSURE_INVENTORY_SEMANTICS_VERSION` **inchangée** : la version entre dans la préimage de `inventory_id` (`gate_v_final_holdout_protocol.py:796`) et le constructeur refuse toute autre valeur (`:435`) ; la relever changerait **tous** les identifiants. Un membre d'énumération ajouté ne modifie la préimage d'aucun finding existant. |
| **F3 d'E3-A** | **inchangé** (le contrôle `dernière clôture <= ws` est dans B3). | classification inchangée. |
| **B2 (scanner)** — omis dans le premier jet de R9 (revue D1, D8) | (a) nouvelle classe `HASHED_FILE` : fichier lu **en flux pour son seul SHA-256**, jamais analysé, plafond de taille et d'effectif ; aujourd'hui `INERT_FILE` « n'est jamais ouvert » et la double passe ne compare que le nom (`gate_v_exposure_scan.py:278`, `_comparable`), donc une altération de `oos_trades.csv` ou d'un checkpoint serait invisible ; (b) un second motif d'orphelin de publication (`.+\.[0-9a-f]{32}\.tmp`), limité par règle aux emplacements du dossier du run et de `walk_forward/**` (le constructeur de `SourceRule` n'accepte aujourd'hui que le motif `EXPOSURE`, `:398-399`) ; (c) nouveaux plafonds de `ScanLimits` (octets hachés) → le bloc `limits` épinglé dans l'A0 change (`_LIMIT_NAMES`). | le `rules_digest` des tables v2/v3/v4 est inchangé (aucune règle existante ne change de classe) ; l'ADR 23.30.4 « B2 inchangé » est **amendé**. Décision D8. |
| **B3** | `gate_v_exposure_interpreters_v5` : règles `CAMPAIGN_DIR` ajoutées **en queue** (table v4 en tête, digest v4 reproductible) : `run_data_coverage.json`, `run_session_NNNN.json`, `run_seal.json` (informatifs stricts) ; orphelins dans le dossier du run ; arbre `walk_forward/**` à motifs fermés en `HASHED_FILE` (sorties scellées : `manifest.json`, `state.json`, `aggregate.json`, `folds/fold_NNN/{definition,selection,test_result}.json` et `{train_candidates,oos_trades,oos_equity}.csv`, `.gate_v_checkpoints_v1/manifest.json` et `folds/fold_NNN.json`) ; paramètre `s0_frame_facts` ; `v5` ajoutée à `KNOWN_B3_VERSIONS` et `B3_RULES_DIGESTS` (`gate_v_exposure_interpreters.py:264-277`). | v2, v3, v4 connues, digests figés ; `RESULTS` et `SPLIT_PLAN_DIR` identiques ; digest `CAMPAIGN_DIR` v5 **à mesurer** (S-5a, jamais présumé). |
| **B5 / A0** | cohérence de l'audit (`gate_v_exposure_store.py`) : `_EXECUTION_KINDS` étendu (`:647`) ; `ABSENCE_ESTABLISHED` accepté **uniquement** pour les deux nouveaux kinds avec référence à une couverture (`:678-679`) ; branche P2 (`:677`) étendue à `VALIDATION_RUN_PRE_HOLDOUT` avec la couverture comme « manifeste » ; **`EvidenceStatus.ESTABLISHED_BY_PARENT`** ajouté (émis pour un dérivé dont le parent est exposé) ; règle de `kind` : un run dont le dossier contient une couverture structurellement valide porte le kind `VALIDATION_RUN_PRE_HOLDOUT` / `VALIDATION_RUN_DERIVED` même non résolu, sinon `UNKNOWN_SOURCE` comme en v4 ; `non_oos_validations` (`:685-693`) n'exige un finding `UNKNOWN_SOURCE` que pour les runs sans couverture ; clé optionnelle `s0_frame_facts` dans `A0_RECORD_KEYS` (tuple fermé, `:88-93`) avec nouvelle version du format d'enregistrement (hors `inventory_id`). | A0 historiques lisibles ; version des règles B3 enregistrée dans l'A0. |
| **Manifest V2** | **aucun changement** (17 clés strictes) ; alternative : D2. | inchangé. |
| **Capture WF** | `walk-forward-capture-v1` et `persist_walk_forward_run` **inchangés**. | inchangés. |
| **ADR** | nouvelle section 23.34 ; 23.30.1 « preuves d'exclusion : aucune à ce jour » → EP-S0 ; 23.30.4 « E3-A inchangé » → amendé ; 23.30.5 : deux questions ouvertes closes. | clauses d'origine non réécrites (renvois). |
| **Comptabilité du multiple testing** | **inchangée**. Limite préexistante rappelée : `train_candidates_evaluated` (candidats par fold) n'entre dans aucune vue de comptabilité ; ce contrat ne la corrige pas. | — |
| **Anciens runs** | sans couverture ⇒ `UNKNOWN_SOURCE` / `WINDOW_UNKNOWN` (comme v4), `content_hash` = hash des octets du run. | identité inchangée. |

---

## 10. Vecteurs de hash (recalculables indépendamment)

Source de vérité : `0025-proposal-E3E-Q2-STAGE2-VECTORS.json` (entrées littérales + hashs). **Octets du run** : les vecteurs publient `validation_run.json` en JSON normatif (déterministe) ; en production le hash porte sur les octets *tels que `save_validation_run` les écrit* (`indent=2`, non trié) — la règle est « SHA-256 des octets exacts publiés », quelle que soit la sérialisation. Recette : JSON compact = `json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` UTF-8 ; JSON normatif = `json.dumps(o, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n"` UTF-8 ; préimage de trame : 3.2. `W = [2026-01-01T00:00:00.000000Z, 2026-04-01T00:00:00.000000Z)`. Vérifié par un programme qui n'importe pas le générateur (`calendar.timegm`, `struct`, `csv`, `hashlib` seulement) : **tous égaux**.

| Vecteur | `source_sha256` | `frame_sha256` | `last_close_utc_exclusive` | Verdict (trame == S0) |
|---|---|---|---|---|
| V1 clôture == `ws` | `8d43f5576f03a0f39ab24409ae9d12152a8a49ab9d48e4af3f1e2e83b8d7dea6` | `cf582fa6884fc5ab0bfae6bd62b126c1ee669ca5ed74d110ce76ca4c475185c7` | `2026-01-01T00:00:00.000000Z` | absence possible (borne exclusive) |
| V2 une barre dans `W` | `7d4b35790084c947faa0a1fc465dbdffbedab8c281c613951ddeec911b3ffdc9` | `974c02e2a8c17ff3aaebad024481e7d35bb364bb481a47bad3c936df38381f4a` | `2026-01-01T00:03:00.000000Z` | **exposition** (P2′) |
| V3 dernière barre à cheval sur `ws` | `51d0e06acd720cc1c90f938e935fea940271448d1c8ff0df35f818650c588486` | `3ea4ae8ea57b37dc9f74ce0c8ea3b2c2daa4b092c1effbeabc523a3095a0bb0d` | `2026-01-01T00:01:00.000000Z` | **exposition** (durée de barre ajoutée) |

Chaîne complète sur V1 (WF, 1 fold, 1 session, 2 sorties) puis MC dérivé :

| Artefact | SHA-256 des octets normatifs |
|---|---|
| `run_data_coverage.json` (WF) | `5e8a1baad41741aec523377a4a366e3849f494a0e7a640f074b12e20c9bae10e` |
| `run_session_0001.json` | `dc011a2adb4caab376fa3212d7a487e78be42b2775f92e6364bf647f33f88cad` |
| `validation_run.json` (WF) | `9a257ab355585ff89e2a847c01f8fbb78beba4594846f9bccf5863d720bfcac4` |
| `run_seal.json` (WF) | `570a679591c5578cdaef24cba3ecff36aa111c97e4931ca77909b405361beea5` |
| `evidence_hash` WF (= `content_hash` du finding) | `131f4b80d8f5dc0605fc1ab3e86d4477a79e753aa558bfc59e3ca4d019d74ff6` |
| `run_data_coverage.json` (MC, `DERIVED`) | `23392b149496eccf6e2013d1eed4cdb4db6d9c79f4636f3921913ddeede680dd` |
| `validation_run.json` (MC) | `5ece0da0b2081c7ca521108601e7329b18bb3baf61000500a196d551c47d1669` |
| `run_seal.json` (MC) | `397d0349dbb2c304ba190e2723bb77f6001c2ae6928ee0fb57274e343aee5514` |
| `evidence_hash` MC | `4a2c743e3855a7a124f9edb1063a596d34133c25561ce54fd80a3ad81598dd42` |
| `s0_frame_facts_sha256` (objet `S0FrameFacts` de V1, entre dans les deux `evidence_hash`) | `cdcdcde70f0316be82734b9d35027ddbb87f21e05ce9c53f58ae7c22de7cb6c3` |

Finding attendu WF : `source_kind = VALIDATION_RUN_PRE_HOLDOUT`, `RESOLVED`, `NO_OVERLAP`, fenêtre `[2025-12-31T23:51:00.000000Z, 2026-01-01T00:00:00.000000Z)`. Finding MC : `VALIDATION_RUN_DERIVED`, mêmes verdict et fenêtre (celle du parent, recalculée).

---

## 11. Matrice RED et résultats d'exécution (prototype de référence, hors production)

Correspondance avec la demande (§7) : exécution antérieure à W → G-01, R2-04 ; recouvrement réel → R2-02 ; exécution postérieure + chargement historique → R2-04 / R2-05 ; couverture manquante ou falsifiée → R2-06, R2-07, R2-08 ; hash S0 correct, trame différente → R2-09, R2-10 ; plusieurs folds dont un exposé → R2-12 ; durée de barre → R2-03, R2-13 ; transformation non tracée → R2-10, R2-11, R2-41 ; parent MC/PS absent ou altéré → R2-26 à R2-45 ; publication partielle → R2-18, section 6.3 ; anciens inventaires → R2-25 + tests B3 v2/v3/v4 (L4) ; source externe non prouvée → R2-15, R2-16.

| Id | Scénario | Attendu |
|---|---|---|
| G-01..04 | parcours positif complet : WF, MC, PS ×2, scellement par récupération (`frame_sha256_after` nul admis **uniquement** dans ce cas) | `NO_OVERLAP` / absence établie |
| R2-02 | la trame contient une barre de `W` | `OVERLAPS` (P2′) |
| R2-03 | dernière barre M3 ouverte 23:58 (clôture 00:01 > `ws`) | `OVERLAPS` |
| R2-04 / 05 | exécution postérieure à `W`, trame historique seule / sans couverture | `NO_OVERLAP` / `UNRESOLVED` |
| R2-06..08 | couverture absente / bornes falsifiées / taille source altérée | `UNRESOLVED` |
| R2-09 / 10 | hash S0 repris mais un prix change / trame tronquée | `FRAME_MISMATCH` |
| R2-11 | chargeur inconnu | `LOADER_UNKNOWN` |
| R2-12 | deux folds, `X_1` recoupe `W` | `OVERLAPS` (P1) |
| R2-13 | barre déclarée 60 s pour des données à 180 s | refus |
| R2-14 | fold à borne naïve | `TIMEZONE_UNKNOWN` |
| R2-15 / 16 | faits S0 absents / d'un autre fichier | `NO_S0_FACTS` / `S0_MISMATCH` |
| R2-17 | octet du run modifié après scellement | `RUN_ALTERED` |
| R2-18 | couverture + run sans Seal | `NO_SEAL` (aucune réparation) |
| R2-19..21 | session absente / de cadre différent / non listée | refus |
| R2-22 / 23 | sortie non scellée / altérée sous `walk_forward/` | `OUTPUT_UNSEALED` / `OUTPUT_ALTERED` |
| R2-24 | fichier inconnu dans le dossier du run | `UNKNOWN_RUN_FILE` |
| R2-25 | ancien run sans couverture | `NO_COVERAGE` (= Étape 1) |
| R2-26..33 | MC/PS : parent absent, altéré, entrée altérée, ensemble non exhaustif, entrée non scellée par le parent, cycle, chaîne, autre campagne | non établi |
| R2-34 | parent exposé | dérivé `OVERLAPS`, fenêtre recalculée |
| R2-35 | Seal de version inconnue | `SEAL_INVALID` |
| R2-36..38 | `plan.json` altéré ; `data_manifest` non déclaré ; déclaration externe à chemin libre | refus |
| R2-39 / 40 | `frame_sha256_after` nul hors récupération / renseigné en récupération | `FRAME_AFTER_MISSING` / `FRAME_AFTER_UNEXPECTED` |
| R2-41 | timeframes mêlés (écarts 60 s et 180 s) avec durée déclarée 180 | `FrameRefused` (`BAR_DURATION_MISMATCH`) |
| R2-42 | MC : rôle `oos_trades:000` détourné vers `walk_forward/manifest.json` | `INPUT_INVALID` |
| R2-43 / 44 | dérivé de type `oos` / `dataset_snapshot_id` différent du parent | `RUN_INVALID` / `DERIVED_SNAPSHOT_MISMATCH` |
| R2-45 | taille épinglée d'une entrée différente de celle scellée | `INPUT_NOT_SEALED_BY_PARENT` |
| R2-46 | orphelins de publication dans le dossier du run et sous `walk_forward/` | consignés, `NO_OVERLAP` conservé |
| R2-47 | faits S0 différents ⇒ `content_hash` différent | identité liée aux faits |

**À écrire avec l'implémentation (non couverts par le prototype)** : RED-DF (le repli de worker échoue quand `data_file` est neutralisé) ; RED-PIN (un accès hors journal fait échouer MC/PS) ; RED-AST (modules feuilles, aucun appel aux fonctions de disque de `validation_run`) ; RED-PARITÉ (digest pandas ↔ stdlib sur fichiers variés, dont la parité exigée sur S0 complet) ; RED-B2 (classe `HASHED_FILE` : flux, plafond, altération d'un CSV détectée par la double passe ; second motif d'orphelin limité à ses emplacements) ; RED-B3 (digests v2/v3/v4 figés, motifs étroits, collision `AMBIGUOUS_SOURCE_TABLE`, orphelins dans le dossier du run) ; RED-T3 (le chemin de reprise sans chargement ne crée aucune session) ; RED-CONC (remplacement concurrent du run avant le Seal, détecté seulement si PC-1 est respectée) ; RED-B5 (A0 historiques lisibles, nouveau bloc, cohérence du relevé) ; RED-E3A (test 8/2/2 amendé, identités des kinds existants inchangées) ; RED-J (E3-J : pas d'admission sans faits S0 recalculés).

**Résultats du prototype** (Python 3.13.7, pandas 3.0.3, numpy 2.2.6) : matrice **52/52** ; digest stdlib == digest pandas (colonne `time` en `datetime64[us]`) ; crash **156/156** ; vecteurs recalculés indépendamment : **tous égaux**.

---

## 12. Autres sources qui empêchent `FRESH` malgré K1 Étape 2 — K1 n'est PAS une garantie suffisante pour Gate V

Constat local (comptage de noms de fichiers, aucun contenu de marché lu) : `results/` contient **43 jobs** dont 43 `config_used.json` et **3** `data_manifest.json`, 2 entrées `validations/`, 3 `dataset_splits/`. Conséquences, toutes déjà inscrites dans l'ADR :
- **Jobs historiques** : §23.30.4 — un job est `OVERLAPS` (P1/P2) ou `UNRESOLVED`, **jamais** `NO_OVERLAP` (aucune preuve d'exclusion pour un job ; 40 des 43 n'ont même pas de `data_manifest.json`). Tant qu'un job existe sous une racine auditée, `FRESH` est inatteignable. **K1 Étape 2 ne traite pas les jobs** ; les retirer ou déplacer est interdit (§23.30.3).
- `ValidationRun` OOS legacy : `UNRESOLVED` (§23.30.4).
- **Sorties hors racines auditées** : `equity_curve.csv` (≈ 50 Mo) et `trades.csv` à la racine du dépôt, ignorés par Git, datés du 2026-05-19, correspondent à un backtest plein-données lancé depuis l'interface (`app.py:6332`). Leur contenu n'a pas été ouvert. Un calcul pouvant avoir accédé à des données couvrant `W` doit résider sous une racine auditée **ou être déclaré** (§23.30.3, 23.11 étape 2) : ces sorties relèvent de la déclaration humaine, que K1 ne remplace pas.
- Sorties du runner V1 sous le dossier de campagne : inconnues et bloquantes en v4 ; elles ne deviennent connues que si l'orchestrateur V2 produit un Seal (section 6).
- Verrou et sentinelle (option C) : bloquants pour toute racine, propre ou étrangère, sans récupération définie pour une racine étrangère.
- **Aucun orchestrateur V2, aucun écrivain public de `RESERVATION` / `ADMISSION` (E3-D), aucun E3-J** : l'admission de bout en bout reste non démontrée.
- Accès hors chemin de données (code de stratégie futur, consultation humaine) : borné seulement par les déclarations (§23.30.1).
- Hypothèse fuseau `naive_utc_declared` : inchangée.
- F3 d'E3-A (`max(time) < ws`, sans durée de barre) : résiduel ; B3 refuse l'exclusion dans ce cas, mais F3 peut afficher « MET » alors que la dernière barre de S0 chevauche `ws` (décision séparée).

**Conclusion** : l'Étape 2 rend l'absence d'exposition d'un WF/MC/PS **démontrable** ; elle ne rend ni `FRESH` atteignable pour le dépôt actuel (jobs), ni Gate V franchissable.

---

## 13. Amendements ADR proposés (texte, à intégrer seulement après acceptation)

**23.34.1 (nouveau) — Preuve d'exclusion EP-S0.** « Une preuve d'exclusion est recevable pour une exécution Walk-Forward si elle est liée au run exact (couverture, sessions et sceau publiés dans le dossier du run, le sceau contenant le hash des octets du run), borne la trame entière chargée par ses faits recalculables (digest de trame, bornes, durée de barre), et égale les faits de S0 recalculés par l'auditeur depuis les octets de S0. Les dates de fold ne sont jamais une preuve d'exclusion. »
**23.34.2 — Dérivés.** MC et PS sont recevables comme dérivés d'un WF scellé selon DC-1 (section 8.2) ; leur verdict est recalculé depuis le parent.
**23.34.3 — Amendements.** 23.30.1 : « Preuves d'exclusion reconnues : aucune à ce jour » → « EP-S0 (23.34.1), pour les seuls WF/MC/PS produits par l'orchestrateur V2 ; aucune pour les jobs ». 23.30.4 : « E3-A inchangé » → « E3-A : deux membres additifs de `SourceKind` ; formules, versions et identités inchangées ». 23.30.5 : « durée de la dernière barre » **traitée dans B3 pour les runs WF/MC/PS** (reste ouverte dans F3 d'E3-A) ; « fuseau de la colonne `time` » : **précisée** (`naive_utc_declared`, déclarée non prouvée) et **non close**. 23.30.4 « B2 inchangé » → amendé (classe `HASHED_FILE`, motif d'orphelin).
**23.34.4 — Compatibilité** : B3 v5, A0, anciens runs (section 9). **23.34.5 — Limites** : section 12. Aucune clause d'origine n'est réécrite (renvois).

---

## 14. Décisions réellement ouvertes

| Id | Question | Recommandation |
|---|---|---|
| **D1** | Accepter l'architecture couverture unique + sessions + Seal, trame S0 **entière** uniquement (pas de sous-trame). | Accepter. |
| **D2** | Épinglage : par la chaîne `inventory_id` (aucun changement de Manifest) ou Manifest V3 avec champs de hash. | Chaîne `inventory_id` + garde D5 additive ; Manifest V3 seulement si l'utilisateur veut un pin direct (touche D2/D4/D5 et la validation stricte de B3). |
| **D3** | Chargeur V2 : `float_precision="round_trip"` (digest recalculable en stdlib) ou parseur par défaut + version de pandas épinglée. | `round_trip`. Parité sur S0 complet vérifiée à l'implémentation (sinon refus). |
| **D4** | Marge de sécurité sur l'hypothèse fuseau (exiger `last_close + marge <= ws`) ou simple déclaration nominative. | Déclaration nominative (F6) sans marge cachée ; toute marge est une valeur de 23.24, non inventée ici. |
| **D5** | Deux `SourceKind` exposants additifs (ajout dans E3-A) et amendement du test 8/2/2. | Accepter. |
| **D6** | Disposition des sorties V1 : reconnaître `walk_forward/**` comme sorties scellées, ou les déplacer sous le dossier du run (choix de l'orchestrateur V2, inexistant). | Garder la disposition V1 (le code PS lit `campaign_dir/"walk_forward"`). |
| **D7** | Risque R-mut : exiger CoW + `frame_sha256_after` non nul pour toute session de calcul. | Exiger pour la session de calcul ; nul accepté pour la récupération. |

| **D8** | Amendement additif de B2 : classe `HASHED_FILE` (flux, SHA-256 seul) et second motif d'orphelin de publication, limités aux emplacements du run et de `walk_forward/**`. Sans lui, `OUTPUT_ALTERED` et les entrées CSV de MC sont invérifiables par le scanner et un crash de `save_atomic` rend un run non prouvable à vie. | Accepter. Alternative dégradée : ne pas sceller les CSV ; la vérification des sorties relève alors d'E3-J seul (B3 ne peut plus affirmer `OUTPUT_*`). |
| **D9** | Lier les sorties à la couverture pour réduire R-fabrication (couverture fabricable après coup pour un run V1) : faire figurer `coverage_sha256` dans le manifeste de capture du WF (clé additive, `walk_forward.py:2155-2165`). Touche `walk_forward.py` (contrat historique) : décision séparée. | Ne pas le faire dans K1 ; le consigner comme durcissement futur de l'orchestrateur V2. |

Hors K1, toujours ouverts : N1-N20 en bloc, valeurs 23.24, E3-F, E3-J, E3-Q, signature détachée avant `REAL`, F3 raffiné d'E3-A.

---

## 15. Plan d'implémentation en petits lots TDD (aucun avant acceptation explicite)

| Lot | Contenu | Dépend de | Statut |
|---|---|---|---|
| **L1** | module pur `gate_v_frame_digest.py` : digest v1, faits de trame, refus ; vecteurs V1-V3 ; parité pandas ↔ stdlib (test) | — | **prochain lot** (aucun fichier existant modifié) |
| **L2** | module pur `gate_v_run_data_coverage.py` : schémas, constructeurs, validateurs stricts de Coverage / Session / Seal / Derived ; octets normatifs ; `evidence_hash` ; vecteurs de chaîne | L1 | prêt après L1 |
| **L3** | vérificateur pur `gate_v_k1s2_verifier.py` (logique du prototype) + matrice RED complète sur arbres synthétiques | L2 | prêt après L2 |
| **L0** | amendement B2 additif : `HASHED_FILE`, second motif d'orphelin, plafonds, `rules_digest` historiques inchangés (tests de figeage) | — | prêt après acceptation de D8 |
| **L4** | B3 v5 : règles, `s0_frame_facts`, findings, relevé, `content_hash` composite, digests v5 mesurés ; v2-v4 inchangées | L3, D5 | prêt après L0, L3 + acceptation |
| **L5** | E3-A : 2 `SourceKind` ; amendement du test 8/2/2 ; B5 : cohérence, bloc A0 | L4 | idem |
| **L6** | `compute_s0_frame_facts` (côté auditeur) + pin | L1 | prêt après L1 ; câblage attestation **BLOQUÉ** (N20 non accepté) |
| **L7** | chargeur V2 à lecture unique, `FrameHandle`, `PinnedReader`, sessions, publication E3-C, R0, C-DF, tests de crash | orchestrateur V2 | **BLOQUÉ** (orchestrateur V2 inexistant) |
| **L8** | garde D5 additive | L2 | prêt après L2 |
| **L9** | E3-J : pas d'admission sans faits S0 recalculés, re-hash des déclarations externes (O-J3) | E3-J | **BLOQUÉ** (E3-J inexistant) |

---

## 16. Risques

**Éliminés par ce contrat** : substitution d'un `DataFrame` ou d'un fichier sous un hash de S0 correct ; filtre ou transformation non tracés ; couverture ou sceau **modifiés après publication** (détecté par les hashs croisés) ; run altéré après scellement ; session de reprise sur une autre trame ; sortie de calcul non scellée ; dérivé MC/PS à entrée non épinglée ou à parent absent, altéré ou cyclique ; dernière barre à cheval sur `ws` ; faux `FRESH` à partir d'un état partiel de crash ; copie arbitraire de fenêtre ; réécriture d'une identité historique.

**Résiduels (nommés, non résolus)** : R-nonprod — la couverture est une **déclaration scellée de l'orchestrateur**, pas une preuve d'exécution (aucune attestation matérielle ; un acteur ayant la main sur le disque peut forger un jeu cohérent : limite générale §23.3, `results/` non versionné) ; R-mut — mutation en place d'une trame partagée par une session crashée (non détectable) ; R-strat — code de stratégie lisant hors chemin de données ; R-tz — hypothèse `naive_utc_declared` ; R-F3 — F3 d'E3-A sans durée de barre ; R-ext — déclarations externes épinglées mais non relues par le scanner ; R-jobs — section 12 ; **R-fabrication** — pour un run produit par le V1, couverture, sessions et Seal peuvent être *fabriqués après coup* de façon cohérente, car aucune sortie de calcul ne référence `coverage_sha256` (D9) : la preuve n'est un témoignage de l'orchestrateur V2 que s'il est la seule voie de production ; R-concurrence — `T3` non exclusif (PC-1) ; R-statique — une altération après `RESERVATION` n'est vue qu'à l'attestation / l'`ADMISSION` / l'étape 13 (5.5).

---

## 17. Revue indépendante et vérification du delta

**Relecteur neuf (agent `general-purpose`, lecture seule, 63 messages, ≈ 16 min 30 s)** : verdict **ACCEPT WITH FIXES** — 1 défaut BLOQUANT, 8 MAJEURS, 3 MINEURS ; aucune refonte. Il a recalculé les vecteurs **depuis la prose seule** (tous égaux), relancé la matrice (alors 43/43), vérifié les numéros de ligne cités et confirmé que l'ajout de deux `SourceKind` préserve les identités (préimage de `inventory_id` : valeurs de `source_kind` seulement ; seul `tests/test_gate_v_final_holdout_protocol.py:55` casse).

| Défaut | Sév. | Traitement dans cette version | Vérifié |
|---|---|---|---|
| D1 B2 ne hache pas les fichiers inertes ; `walk_forward/**` est surtout du CSV ; « B2 inchangé » faux | BLOQUANT | amendement B2 additif (section 9, **D8**, lot L0) ; alternative dégradée nommée | code relu (`scan.py:278`, `:398-399`) ; non testable avant L0 |
| D2 durée de barre « mesurée » non sûre (barres 60 s mêlées à du 180 s) | MAJEUR | durée **déclarée** = plus petit écart mesuré (3.3) | reproduit avant correction ; RED R2-41 |
| D3 `frame_sha256_after` nul accepté sans condition | MAJEUR | nul ⇔ récupération (5.3, 4.6) | RED R2-39, R2-40 |
| D4 sur-affirmation « couverture inventée après coup : éliminée » | MAJEUR | affirmation retirée ; **R-fabrication** nommé ; durcissement **D9** | relecture |
| D5 faits S0 hors identité | MAJEUR | `s0_frame_facts_sha256` dans `evidence_hash`, uniforme dès qu'une couverture existe (5.5) | RED R2-47 ; vecteurs régénérés |
| D6 dérivés trop lâches (rôle détourné, type, snapshot, taille) | MAJEUR | table fermée rôle → (origine, chemin) ; type et snapshot égaux ; taille vérifiée (5.4) | RED R2-42..45 |
| D7 §8.1 faux (plan de split, `manifest.json`, relectures, séquence) | MAJEUR | table réécrite ; `manifest.json` exempté ; ordre lire → épingler → calculer (6.2) | code relu ; relecture |
| D8 orphelins `.tmp` bloquants à vie | MAJEUR | second motif d'orphelin limité à ses emplacements (B2, **D8**) | RED R2-46 (prototype) ; non testable sur B2 avant L0 |
| D9 amendements B5/A0 incomplets | MAJEUR | liste complète (section 9 : `A0_RECORD_KEYS`, `ESTABLISHED_BY_PARENT`, branche P2, règle de `kind`, `KNOWN_B3_VERSIONS`, composite uniforme) | relecture |
| D10 `T3` non exclusif ; reprise sans chargement ; E3-C | MINEUR | PC-1, `R-concurrence`, chemin sans session, `PUBLISHED_UNCONFIRMED`, profil `SIMULATED` (6.2) | relecture |
| D11 inexactitudes factuelles (`engine.py`, checkpoints, ligne 1226, C-8, clôture 23.30.5) | MINEUR | corrigées (4.2, 4.4, C-7, C-8, 13) | relecture ; numéros de ligne revérifiés |
| D12 sorties hors racines auditées oubliées (`equity_curve.csv`, `trades.csv`) | MINEUR | ajoutées à la section 12 (contenu non ouvert) | relecture |
Précisions du relecteur intégrées : dialecte CSV et correspondance trame → kind (3.2) ; octets du run (10) ; limite de `static_sources_digest` pour `NO_OVERLAP` (5.5).

**Vérification ciblée du delta définitif (par l'auteur, NON indépendante).** Relancés après correction : matrice **52/52**, simulation de crash **156/156** (0 état partiel classé « absence établie »), parité stdlib ↔ pandas 3.0.3, recalcul indépendant des vecteurs régénérés **tout égal**. Recherche de formulations périmées dans le document (cas G-05, plages de cas, « 43 cas ») : deux références corrigées. **Non relu par un second relecteur** : les sections 5.4 (table fermée), 6.2 (réécrite), 8.1 (réécrite), 9 (lignes B2 et B5) et 14 (D8, D9) ; ces textes n'ont été vérifiés que par leur cohérence avec le prototype et le code. **Non testé** : tout ce qui touche B2/B3/B5/E3-A réels (aucun code de production n'a été écrit). **Non relu par le relecteur** : l'ADR §23.33 en détail, B6, E3-J, le registre E3-D, les tests existants (hors celui en 8/2/2), les 156 scénarios de crash, le CSV réel (jamais ouvert au-delà de l'en-tête et des 30 000 premières lignes de 2017-2018), `monte_carlo.py` et `parameter_stability.py` (recherche textuelle seulement).
