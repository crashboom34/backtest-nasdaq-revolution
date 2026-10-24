# E3-E — K1 Étage 2 : contrat de conception de la preuve d'exclusion des validations pré-holdout — PROPOSED, NON NORMATIF, NON ADOPTÉ, NON IMPLÉMENTÉ

**Statut (2026-10-24).** Contrat de conception **séparé** de l'Étage 1 (ADR 0025 23.33, accepté et implémenté). Il n'est **pas** accepté : l'utilisateur a explicitement exclu l'Étage 2 de l'autorisation du 2026-10-24. Rien ici n'est codé ; aucun contrat historique de WF/MC/PS n'est modifié ; aucune preuve d'exclusion partielle n'est introduite. `REAL` = DISABLED / NOT QUALIFIED · `GATE V` = NON PASSÉE · `FINAL_HOLDOUT` = NON ACCÉDÉ. Prérequis de l'Étage 2 selon R8 : PR-1 à PR-5.

## 1. Principes non négociables
1. Aucun résultat inconnu ne devient une absence d'exposition prouvée. Sans preuve complète ⇒ l'Étage 1 s'applique (`UNKNOWN_SOURCE`, `UNDETERMINED`).
2. La fenêtre d'exécution `X` n'est jamais assimilée à la fenêtre accessible au calcul `A` (23.30.1). `max(effective_test_end) > ws` n'est ni une preuve d'établissement, ni une preuve d'exclusion, ni un critère.
3. Une preuve d'exclusion est **liée au run exact** (hash du `ValidationRun`) et borne **toutes** les données accessibles : chargées, tronquées, warm-up et TRAIN compris, durée de la dernière barre comprise.
4. Aucune fenêtre n'est copiée d'un artefact vers un autre sans contrat explicite (DC-1).
5. Le run reste identifiable, haché et audité dans tous les cas, y compris quand son absence d'exposition est établie (un finding `RESOLVED`/`NO_OVERLAP` garde son hash dans `inventory_id`).

## 2. Identité du run
`run_record_hash` = SHA-256 du JSON canonique du `ValidationRun` persisté (hash déjà porté par le finding : `content_hash`). `validation_run_id` = `gate_v_v2_<64hex>_{walk_forward|monte_carlo|parameter_stability_fold_NNN}`, égal au nom de répertoire, scopé à la campagne et référencé par le Manifest (D5). Toute preuve Étage 2 cite `validation_run_id` **et** `run_record_hash` ; un run modifié invalide la preuve.

## 3. Données effectivement chargées (PR-1)
Un enregistrement **`RunDataCoverage`** (`gate_v_run_data_coverage_v1`), écrit par le futur orchestrateur V2 (inexistant : le V1 sert de gabarit), **calculé sur le `df` réellement passé** au calcul et non lu dans un `BacktestManifest` fourni séparément, publié exclusivement (E3-C) dans le dossier audité et **épinglé par le Manifest**. Champs : `coverage_semantics_version`, `validation_run_id`, `run_record_hash`, `dataset_snapshot_id`, `loaded_content_sha256`, `loaded_row_count`, `bar_duration_seconds`, `loaded_first_open_utc`, `loaded_last_open_utc`, `loaded_last_close_utc_exclusive` (= dernier `open` + durée de barre), `execution_window` (`start`, `end_exclusive`, informatif). Instants ISO-8601 UTC offset-aware à la microseconde. Le warm-up et la phase TRAIN sont dans la couverture : `loaded_first_open_utc` est la première barre chargée, pas `train_start`.

## 4. Couverture complète accessible au calcul, durée de barre et fuseaux
`A_run = [loaded_first_open_utc, loaded_last_close_utc_exclusive)` demi-ouvert. La colonne `time` du jeu de données est naïve et interprétée UTC (contrat de `engine._add_market_time_columns`, déclaré non prouvé en 23.3) : l'amendement fixe cette règle pour la couverture et refuse tout enregistrement dont les instants sont naïfs, hors UTC non explicite, non monotones (`first < last`), de durée de barre non positive, ou de `loaded_row_count` nul. La durée de la dernière barre est **toujours** ajoutée (ferme la question ouverte « durée de la dernière barre dans F3 », 23.30.5) ; F3 raffiné : `s0_max_time_utc + bar_duration_seconds ≤ ws`, fait épinglé par l'attestation (N20).

## 5. Verdicts d'un WF (trois états de 23.30.1)
| Condition | Verdict |
|---|---|
| un fold `X_k = [train_start_k, effective_test_end_k)` recoupe `W` (P1), ou `A_run ∩ W ≠ ∅` (P2) | **exposition établie** (`RESOLVED`, `OVERLAPS`, fenêtre = enveloppe des `X_k` chevauchants ou `A_run`) |
| `RunDataCoverage` valide, liée au run exact, `loaded_content_sha256` = hash de `S0`, `dataset_snapshot_id` dérivé par `build_local_csv_snapshot_id`, `loaded_last_close_utc_exclusive ≤ ws`, F3 raffiné, aucun fold chevauchant | **absence établie** (`RESOLVED`, `NO_OVERLAP`) |
| toute autre situation (couverture absente, illisible, non liée, hash différent, bornes naïves ou inversées, fold après `W` avec historique visible, couverture incomplète) | **absence non établie** (`UNRESOLVED`, Étage 1) |

## 6. MC et PS : entrées, parents, provenance (PR-4, DC-1)
MC et PS sont des modules feuilles sans lecture de fichier (preuve statique, RED R-Q2-13 y compris l'absence d'appel aux fonctions de disque de `validation_run`). L'orchestrateur relit toutefois des artefacts d'entrée (V1 : `folds/<id>/oos_trades.csv`). La preuve dérivée **épingle le `sha256` de chaque artefact d'entrée** et référence le parent par `source_validation_run_id` + `run_record_hash` du parent (PS : aussi `source_fold_id`). **DC-1** : `exposition(dérivé) ⊆ exposition(parent)` ; `absence(dérivé)` ⇔ `absence(parent)` établie ∧ module feuille ∧ hashs d'entrée égaux à ceux du parent ; **aucune fenêtre n'est copiée** (le dérivé porte `parent_run_id`, pas de fenêtre propre). Parent absent, illisible, en double, cyclique, d'une autre racine ou d'une autre campagne ⇒ non résolu.

## 7. Deux `SourceKind` additionnels (E3-A, additif)
`VALIDATION_RUN_PRE_HOLDOUT` (exposant : un WF lit des données) et `VALIDATION_RUN_DERIVED` (MC/PS). Valeurs nouvelles uniquement : aucune identité historique ne change. Conséquences : `test_source_kind_has_twelve_values_split_8_2_2` à amender, ADR 23.30 (« E3-A inchangé ») à amender explicitement, idéalement une version d'inventaire ; un producteur d'`ABSENCE_ESTABLISHED` (23.30.5) ; B3 v5 (nouvelle version, digests v2/v3/v4 figés).

## 8. Vecteurs indépendants (conception ; à recalculer par une implémentation indépendante)
Recette : JSON canonique `sort_keys`, séparateurs `(",", ":")`, `ensure_ascii=False`, UTF-8, SHA-256. `W = [2026-01-01T00:00:00.000000Z, 2026-04-01T00:00:00.000000Z)`, `bar_duration_seconds = 180`, `loaded_content_sha256 = "a"×64`, `validation_run_id = gate_v_v2_<"ab"×32>_walk_forward`, `dataset_snapshot_id = "S0"`, `loaded_first_open_utc = 2024-01-01T00:00:00.000000Z`. Champs non listés ci-dessous : ceux du section 3 sans `run_record_hash` ni `execution_window` (vecteurs de forme ; ils s'ajouteront avec le contrat final).
| Vecteur | `loaded_last_open_utc` | `loaded_last_close_utc_exclusive` | `loaded_row_count` | Verdict attendu | SHA-256 de l'enregistrement |
|---|---|---|---|---|---|
| V1 avant `W` | 2025-12-31T23:57:00Z | 2026-01-01T00:00:00Z | 1000 | absence établie (si PR-2/PR-3 vrais) | `0fc3f3e6ec18d3591d066f3cf43c38ae4e1cf94496eae60c6c292e000bf36889` |
| V2 clôture = `ws` | 2025-12-31T23:57:00Z | 2026-01-01T00:00:00Z | 1001 | absence établie (borne exclusive) | `696c4ccddc5a76015e90a82cfb4b6dbed348c36e0bfdf558624b0c392cfee603` |
| V3 une barre dans `W` | 2026-01-01T00:00:00Z | 2026-01-01T00:03:00Z | 1002 | **exposition établie** (P2) | `9801faea6eef76c98ee7cfc1cdc2f54bd218a629749ff4c7a9cce5d2378828f5` |

V1 et V2 ne diffèrent que par `loaded_row_count` (hash distinct, même verdict) ; V3 prouve que la durée de barre est ajoutée.

## 9. Cas RED nécessaires (à écrire avec l'Étage 2, jamais avant sa décision)
R2-01 couverture valide avant `W` ⇒ absence établie, hash conservé dans `inventory_id` · R2-02 clôture exactement `ws` ⇒ absence (borne exclusive) · R2-03 une barre qui s'ouvre à `ws` ⇒ exposition · R2-04 couverture absente/illisible/non liée au run ⇒ Étage 1 · R2-05 `loaded_content_sha256` ≠ hash de `S0` ⇒ pas d'exclusion · R2-06 bornes naïves, fuseau non UTC, `first ≥ last`, barre ≤ 0, lignes = 0 ⇒ refus · R2-07 fold recoupant `W` ⇒ exposition (P1) même avec couverture disjointe · R2-08 fold après `W` sans couverture ⇒ non établie · R2-09 warm-up recoupant `W` ⇒ couverture le détecte · R2-10 TEST seul mais chargement plus large ⇒ `A_run` gouverne · R2-11 `run_record_hash` modifié ⇒ preuve invalide · R2-12 MC/PS : parent absent, double, cyclique, autre campagne, hash d'entrée différent ⇒ non résolu ; aucune fenêtre copiée · R2-13 F3 raffiné `s0_max_time + barre > ws` ⇒ pas d'exclusion · R2-14 identités historiques inchangées, v2/v3/v4 lisibles · R2-15 vecteurs V1-V3 recalculés indépendamment · R2-16 un run dont l'absence est établie reste dans `inventory_id` et A0.

## 10. Interdits
Pas de preuve d'exclusion partielle ; pas de critère `max(effective_test_end) > ws` ; pas de modification du contrat de WF/MC/PS historiques avant décision séparée ; pas de fenêtre dérivée copiée ; pas d'implémentation avant acceptation explicite et prérequis (orchestrateur V2, `RunDataCoverage`, E3-J).
