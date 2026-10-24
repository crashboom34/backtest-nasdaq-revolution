# E3-E S-0 — Q-2 et couverture B3 v4 du dossier de campagne V2 — NON NORMATIF, NON ADOPTÉ (R7, delta de R6)

**Statut : proposition soumise à l'acceptation explicite de l'utilisateur (2026-10-24).** Elle complète et, sur deux points (N8, C-29), remplace le texte de R6 (`…-N1-N20-FINAL-MATRIX.md`, `…-23.32-…`). `REAL` = DISABLED / NOT QUALIFIED · `GATE V` = NON PASSÉE · `FINAL_HOLDOUT` = NON ACCÉDÉ. Checkpoint `ecc7e8d0ec47cbde2c89ab10cc765d3d80a5748c`. Aucune valeur de 23.24 n'est adoptée. **Mise à jour 2026-10-24 (R8)** : les sections 3 (Q2-D1) et 4 (Q2-D1/D2/D3) ci-dessous sont **remplacées** par `0025-proposal-E3E-Q2-FINAL-CONTRACT-PROPOSED.md` (la variante K1 « fenêtre dérivée » du présent document est abandonnée ; historique conservé). **Q-2 n'est PAS close** : sa clôture exige une décision de l'utilisateur (section 4) car ni le dépôt ni l'ADR ne permettent de la trancher sans amender 23.30.1 et E3-A.

## 1. Démonstration (B3 v3 réel, fixtures synthétiques en dossier temporaire)
Script : `scratchpad/q2_demo.py` (hors dépôt), interpréteur `.venv`, `holdout_window = W` synthétique, racine `CAMPAIGN_DIR`.
| Contenu du dossier | `complete` | raisons | findings |
|---|---|---|---|
| `plan.json` seul | True | — | 0 |
| + `manifest.json` | False | `UNKNOWN_ENTRY:…/manifest.json` | 1 `UNKNOWN_SOURCE` |
| + `manifest.update.lock` | False | `UNKNOWN_ENTRY:…/manifest.update.lock` | 1 `UNKNOWN_SOURCE` |
| + `technical_failure.json` | False | `UNKNOWN_ENTRY:…/technical_failure.json` | 1 `UNKNOWN_SOURCE` |
| + `validations/<run>/validation_run.json` (WF ou MC) | False | `UNKNOWN_ENTRY:…/validations` (répertoire inconnu, **jamais descendu**) | 1 `UNKNOWN_SOURCE` |

Conséquence : tout dossier V2 réel (qui contient `manifest.json` dès D4) est `UNDETERMINED`, pour la campagne courante comme pour toute autre. La voie `WINDOW_UNKNOWN` de `_interpret_validation` n'est atteinte qu'en disposition `RESULTS`, jamais dans un dossier de campagne.

## 2. Faits établis (producteur, étage, sens)
- **Producteurs** : `gate_v_campaign_manifest_v2.py` (création exclusive de `manifest.json` ; verrou `manifest.update.lock` `O_EXCL` transitoire ; sentinelle `technical_failure.json` dont **l'existence est le fait** ; preuves `validations/<run_id>/validation_run.json`), plan V2, Claim d'E2, `exposure/**` d'E3-B. Le prédicat D5 `assert_gate_v_pre_holdout_evidence_complete` refuse sur verrou, sentinelle ou marqueur ; l'ADR l'exige avant et après le Claim (étapes 5 et 8 bis, l.1670-1682) et le spec E3-E avant la `RESERVATION`.
- **WF** lit des données de marché : tranche test `[effective_boundary, effective_test_end)` **fin exclusive pour tous les folds** (`walk_forward.py` ~l.718) ; le moteur laisse tout l'historique antérieur à `start` visible (`engine.py` 138-142) et tronque à `<` fin (152-158). **MC et PS** sont des modules feuilles (n'importent ni `engine`, ni `optimizer`, ni `dataset_split`) : aucune donnée de marché, leur fenêtre est celle de leur source (`source_validation_run_id` ; PS aussi `source_fold_id`) ; leurs enregistrements ne portent aucune date.
- **ADR 23.3** définit `E` comme « l'union des fenêtres de **toute exécution ou lecture connue ou déclarée** » avec une liste entre parenthèses qui ne cite pas WF/MC/PS : **leur exclusion de `E` n'est pas démontrée par l'ADR** (hypothèse écartée). **23.30.1** n'admet une preuve d'exclusion que « liée à l'exécution auditée » et bornant toutes les données accessibles, durée des barres comprise ; les étapes 3-4 du verdict interdisent `NO_OVERLAP` sans elle ; Q-2 est ouverte (l.3307, 3564).
- **Comptabilité** : `_count_trials` utilise des vues `CampaignTrialsView` fournies par l'appelant (identités de `research_run`/stratégie par campagne), **pas** les findings de B3 : aucune modification de B3 n'affecte les compteurs.
- **Identités** : `inventory_id` hache **tous** les findings non absorbés, `NO_OVERLAP` compris ; seul `static_sources_digest` écarte `NO_OVERLAP`. Un informatif n'entre dans aucun des deux. Un finding supprimé fait donc **perdre la trace de hash** dans `inventory_id` et A0.
- **Invariant B5** : chaque note `non_oos_validations` exige un finding `UNKNOWN_SOURCE` de même hash.

## 3. Classification par famille (règle B3 v4 proposée)
Classes : S structurel · I informatif · X exposant · T transitoire · U inconnu.
| Famille | Producteur · étage | Sens scientifique | Cl. | Absent / illisible / malformé / dupliqué / altéré · effets | Règle v4 |
|---|---|---|---|---|---|
| `plan.json` | plan V2 · création | ancre | I | absent : `MISSING_REQUIRED` ; autres anomalies : `INFORMATIVE_UNRESOLVED` ; effet sur `complete` seulement | inchangée (v3) |
| `manifest.json` | D4 · après le plan | pointeurs et marqueurs d'exécution, muable (révision) | I | absent légal (avant D4) ; illisible, mal formé, `campaign_id` ≠ nom : `INFORMATIVE_UNRESOLVED` ; altération relue par D5 ; hors `inventory_id`/digest (muable) | `INFORMATIVE_JSON` objet, tag `campaign.manifest`, contrôle `campaign_id == nom du dossier` ; conformité complète = D5 |
| `manifest.update.lock` | D4 · transitoire | aucune donnée | T | nature fausse : `KIND_MISMATCH` → finding ; lien ou point d'analyse : refus de scan B2 ; effet nul sur identités ; résiduel refusé par D5 (étapes 5, 8 bis, 13, 14 bis) | `INERT_FILE`, tag `campaign.manifest_lock` (jamais ouvert) |
| `technical_failure.json` | D4 · échec technique pré-holdout | fait d'audit permanent, aucune donnée de marché | I (audit) | l'existence est le fait, contenu indifférent ; effet nul sur identités ; D5 refuse la campagne | `INERT_FILE`, tag `campaign.technical_failure`, **sans raison d'incomplétude** (un échec ancien d'une autre campagne ne doit pas bloquer tout le programme) — variante durcie : Q2-D3 |
| `validations/`, `validations/<run_id>/` | D4 · après exécution | structure | S | répertoire inconnu aujourd'hui | `STRUCTURAL_DIRECTORY` ×2, ancre `validation_run.json` |
| `validation_run.json` OOS | AF-V-01 | exécution sur la zone de validation | X | schéma/illisible : finding `UNKNOWN_SOURCE` ; hash dans `inventory_id` | interpréteur `VALIDATION_RUN_OOS` inchangé (inclusif) — emplacement : Q2-D2 |
| `validation_run.json` WF | `walk_forward` | lit des données jusqu'à `effective_test_end` | X | voir section 4 | **dépend de Q2-D1** |
| `validation_run.json` MC / PS | `monte_carlo` / `parameter_stability` | post-traitement de résultats, aucune donnée de marché | X (dérivé) | idem | **dépend de Q2-D1** |
| `final_holdout_access_claim.json` | E2 · après ADMISSION | Claim | X | v3 | inchangée |
| `exposure/**` | E3-B | audit | I/T | v3 | inchangée |
| artefacts E3-E à la racine (`prospective_commitment`, `s0_provenance_declaration`, `reservation_time_proof`, `holdout_snapshot_attachment`, `commitment_void_record`, `acquisition_authorization_<seq4>`, orphelin `.exposure.tmp.<32hex>`) | E3-E · dès la `RESERVATION` | engagement, preuves, autorisation | I/T | `INFORMATIVE_UNRESOLVED` | règles R6 (N8) inchangées ; tags `campaign.commitment/s0_provenance/time_proof/attachment/void/authorization` |
| `read_intent.json`, `data_receipt.json`, `final_holdout_closing_record.json` | E3-J/E3-Q · après Claim | exposants | U | `UNKNOWN_ENTRY` | restent inconnus : aucun producteur n'existe ; le Claim établit déjà l'exposition |
| temporaires atomiques `manifest.json.<hex>.tmp`, `validation_run.json.<hex>.tmp` | `atomic_json_store` | transitoires | U | `UNKNOWN_TEMP_FILE`, bloquant transitoire | restent inconnus (B2 impose le motif `EXPOSURE_TEMP_ORPHAN_PATTERN` ; pas de nouveau `TempNaming`) |
| sorties V1 (`walk_forward/**`, `.gate_v_checkpoints_v1`), tout nom inconnu | runner V1 | — | U | `UNKNOWN_ENTRY` | restent inconnus (aucune liste blanche) |

## 4. Décision Q-2 à trancher
Première variante (K2 : « fenêtre disjointe ⇒ aucun finding ») **rejetée** par la relecture indépendante : (i) contredit 23.30.1 et le traitement par B3 des OOS/jobs disjoints (`UNRESOLVED`, absence non établie) ; (ii) fait disparaître le hash de `inventory_id` et de A0 (la justification « comme NO_OVERLAP » était fausse) ; (iii) borne basse `min(train_start)` fausse (l'historique antérieur reste visible) ; (iv) portée trop large (`_interpret_validation` global changerait `RESULTS` sous un digest inchangé).
- **Q2-D1 (décision de l'utilisateur ; recommandation K1)** — **K0** laisser WF/MC/PS inconnus (sûr ; tout dossier V2 réel reste `UNDETERMINED`, GATE V inatteignable) ; **K1 (recommandée)** ajouter un `SourceKind` additif d'E3-A (p. ex. `VALIDATION_RUN_DERIVED`) et amender 23.30.1 par une preuve d'exclusion explicite ; **K2** rejetée.
- **Contenu K1 proposé** : (a) *WF* : fenêtre bornée par le haut seulement, chevauchement ⇔ `max(effective_test_end) > ws` (demi-ouvert, aucune borne basse) ; exigences : `execution_status == completed`, agrégat non nul, `fold_NNN` contigus, `definition.fold_id == fold_id`, instants offset-aware, `train_start < effective_boundary < effective_test_end`, `effective_test_end` jamais `requested_test_end` ; un finding **toujours émis** (`RESOLVED` `NO_OVERLAP`, ou chevauchement ⇒ `RETROSPECTIVE_EXPOSED`), son hash reste dans `inventory_id` ; (b) *MC/PS* : fenêtre de la source résolue **dans la même racine**, par nom de répertoire = `validation_run_id`, identifiants bornés à `<campagne>_<type>[_fold_NNN]`, sans cycle, chaîne aboutissant à un WF ou OOS dérivé, `source_fold_id` présent dans les folds du WF ; sinon `UNKNOWN_SOURCE` ; l'hypothèse « feuille sans donnée de marché » est démontrée par un test de fermeture d'imports (RED) ; (c) dérivation limitée à un tag de la disposition `CAMPAIGN_DIR` (RESULTS et digests v2/v3 inchangés) ; (d) l'ajout d'un membre d'énumération ne change aucune identité existante mais exige l'acceptation (amendement 23.32.13) et la mise à jour des tables B5/magasin.
- **Q2-D2** : fichier OOS V2 — l'ADR (l.2437) parle de `validations/<oos_id>.json`, le code D4 de `validations/<run_id>/validation_run.json` ; à trancher par un test RED sur un dossier produit par le vrai producteur (la coexistence des deux règles provoque `AMBIGUOUS_SOURCE_TABLE`).
- **Q2-D3** : sentinelle INERT sans raison (recommandé) ou avec raison `CAMPAIGN_FAILURE_MARKER` (durcit mais une défaillance ancienne bloquerait tous les inventaires).

## 5. Couverture B3 v4 et étages
v2/v3 intacts ; `B3_RULES_DIGESTS` : RESULTS et SPLIT_PLAN_DIR identiques à v3, CAMPAIGN_DIR nouveau — **`rules_digest` v4 non calculé (la table dépend de Q2-D1/D2) : à mesurer en S-5a, jamais inventé**.
| Étage | Fichiers possibles | K1 acceptée | K0 |
|---|---|---|---|
| avant `RESERVATION` | plan, manifest, validations, sentinelle/verrou éventuels | `complete` si chaque dérivation réussit ; sinon `UNDETERMINED` | `UNDETERMINED` |
| après `RESERVATION` | + engagement, `s0_provenance`, `time_proof`, orphelin | idem (informatifs) | idem |
| avant ADMISSION | + autorisation, attestation, `attachment` | idem | idem |
| après ADMISSION | + admission (registre) | idem ; D5 8 bis garde le manifest | idem |
| après Claim | + Claim (absorbé), `read_intent` inconnu | exposition établie par le Claim | idem |

## 6. N1–N20 et C-16 après Q-2
Seules **N8** (périmètre de B3 v4) et la qualification **C-29** (Lot 1) changent : N8 = « v4 additif de R6 + règles du dossier V2 de la section 3 » ; C-29 ne se lève que par Q2-D1 acceptée **et** mesure de S-5a. Pour N1–N7, N9–N20 et C-16 : aucun conflit relevé (aucune ne dépend des tables de dossier de campagne au-delà de N8). Orientations conservées : N4 option C (aucun droit implicite, aucun nouvel abandon opportuniste), N10 chaîne de slots d'autorisation, N18 chaînes décimales typées + compatibilité de hash historique, N19 vue F1 non persistable (la preuve que le retour scalaire ne contourne pas les gardes B5/E3-J reste une obligation RED R-24/R-71/R-72, **non démontrée ici par du code**), C-16 `seq >= 0`. Le texte R6 de ces décisions n'est pas modifié. Le delta (N8, C-29, Q2-D1..D3) a reçu une relecture indépendante (REJECT de K2, K1 recommandée) mais **sa forme corrigée n'a pas été relue une seconde fois** : aucune révision n'est figée.

## 7. Premier lot TDD (après acceptation du Lot 1)
S-0b (C-16 : une ligne B4 + test) → S-1 vecteurs V1–V10 indépendants → S-2 attestation → S-4 autorisation → S-5a B3 v4 : RED d'abord sur la section 3 (fixtures de `q2_demo.py` étendues, dossier produit par les vrais producteurs D4), **sans** K1 tant que Q2-D1 n'est pas tranchée. Hors lot : F1 (Lot 2), temps/attachment/témoin (Lot 3), tout vérificateur réel, E3-J.

## 8. Reste bloqué ou impossible
Valeurs 23.24 · E3-F (IngestionRecord) · E3-J (11 bis, détection locale du Claim, `ClosingView`) · E3-Q (rapport de qualification) · signature détachée avant `REAL` · mesure `rules_digest` v4 · Q2-D1, Q2-D2, Q2-D3. **Aucune approbation de conception ne qualifie `REAL`.**

## 9. Périmètres de commits documentaires proposés (aucun créé)
D1 : les 7 fichiers `0025-proposal-E3E-*` + ce fichier (8 fichiers). D2 : `AI_HANDOFF.md`, hunk additif §64-§66 seul (sans les hunks étrangers §48-§51 ni `CONTEXT.md`). D3 : intégration ADR après acceptation (23.32.x, 23.32.13, amendements). Jamais `git add .`/`-A` ; empreinte d'index à préserver.
