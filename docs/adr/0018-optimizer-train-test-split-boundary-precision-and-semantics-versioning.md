# Correction du split TRAIN/TEST de l'Optimizer : frontière exacte, décision D1, versioning

Status: Accepté

**Contexte** : `optimizer.py::compute_split_dates()` tronquait `train_end`/`test_start`/
`test_end` en chaîne `"YYYY-MM-DD"` (perte totale de l'heure), puis `engine.run_backtest()`
interprétait ces dates en filtrage **fermé** sur des timestamps minuit — créant un trou temporel
silencieux d'au moins une journée de marché autour du split, jamais signalé. Quantifié
empiriquement (audit read-only préalable, exemple synthétique 7 jours M3, split au jour 3/7) :
**28.6% des barres perdues, ni TRAIN ni TEST**, réparties en deux défauts indépendants (le jour du
split entièrement perdu ; le dernier jour du dataset entièrement perdu de TEST). Le moteur
(`engine.run_backtest(end_boundary=)`, Dette B, DONE) sait désormais représenter explicitement
`[start,end]` ou `[start,end)` — cette correction en tire parti.

## Décision 1 — `TrainTestWindows` remplace le tuple `(train_start, train_end, test_start, test_end)`

Nouvelle dataclass frozen `TrainTestWindows(train_start: str, boundary: str, test_end: str)`,
champs ISO-8601 complets (`.isoformat()`, offset et fraction de seconde préservés — jamais une
troncature à la date). Invariant **unique**, jamais deux valeurs indépendantes pouvant diverger :
la même `boundary` est à la fois la fin EXCLUSIVE de TRAIN et le début INCLUSIF de TEST —

```text
TRAIN = [train_start, boundary)
TEST  = [boundary,    test_end]
```

Une bougie exactement à `boundary` appartient donc toujours à TEST, jamais aux deux, jamais à
aucune. Champ nommé `boundary` (pas `split_boundary`) pour éviter toute collision avec
`dataset_split.py::SplitBoundary` (Track R, concept totalement différent — `CONTEXT.md` documente
déjà l'ambiguïté du mot "split" dans ce dépôt).

**Options considérées** : un tuple étendu à 4 chaînes (rejeté — convention d'inclusivité
implicite, ordre fragile, la classe de bug corrigée ici vient précisément d'une représentation
trop faible) ; réutiliser `ExecutionWindow` existant (rejeté — concept différent, `ExecutionWindow`
décrit une sélection physique de lignes, pas une frontière logique de split).

## Décision 2 — `split_date` (méthode "date") = premier jour de TEST (D1)

Le code historique (`test_start = split + 1 jour`) suggérait une intention D2 ("`split_date` =
dernier jour du TRAIN"), mais l'effet réel mesuré n'honorait NI D1 ni D2 (le jour du split était
perdu dans les deux cas). Aucune documentation/UI n'arbitrait la question avant cette mission.
**Décision retenue, scientifique et non une restauration d'intention certaine** : `split_date` =
premier jour de TEST, à 00:00 Europe/Paris — cohérent avec la méthode ratio (qui produit
naturellement une frontière "premier instant de TEST") et avec la sémantique déjà déclarée par
`dataset_split.py::SplitBoundary` (`[start,end)`). Libellé UI clarifié en conséquence (`app.py`) :
"Premier jour de la période test" au lieu de l'ancien "Date de séparation", ambigu.

## Décision 3 — ratio de durée temporelle préservé, validation stricte ajoutée

`train_ratio` reste un ratio de **durée temporelle** (`Timedelta(seconds=duration*ratio)`),
jamais un ratio du nombre de barres — aucune preuve d'une intention différente, comportement
historique préservé à l'identique. Nouveau : validation stricte `0 < train_ratio < 1` et
`global_start < boundary < global_end` (train/test actif) — `ValueError` explicite plutôt qu'une
fenêtre TRAIN ou TEST vide masquée silencieusement (dataset vide, une seule barre, `split_date`
hors période ou confondu avec une extrémité).

## Décision 4 — versioning explicite de la sémantique + garde de reprise cross-version

`TRAIN_TEST_SEMANTICS_VERSION = "exact-boundary-v2"` (distincte de `git_commit`, déjà capturé
automatiquement par `data_manifest.json` : `git_commit` identifie le logiciel exact,
`TRAIN_TEST_SEMANTICS_VERSION` identifie le contrat scientifique train/test, en principe
indépendant du reste du logiciel). Persistée automatiquement dans `config_used.json` pour tout
nouveau job train/test — propriété logicielle/reproductible, jamais une option UI.

`validate_resume_train_test_semantics()` refuse explicitement une reprise (`resume_run_id`) si le
run courant active train/test et que le job source n'a pas la MÊME version (absente = "legacy",
job antérieur à cette correction) — jamais un mélange silencieux de scores TRAIN/TEST calculés
sous deux contrats de frontière différents au sein d'un même run repris. Une reprise sans
train/test n'est jamais bloquée par cette garde, quelle que soit la source.

## Décision 5 — fenêtre résolue persistée dans `meta.json`

`meta.json` gagne un champ `train_test_windows` (`train_start`/`boundary`/`test_end`/
`train_end_boundary="exclusive"`/`test_end_boundary="inclusive"`) — absent jusqu'ici de tout
artefact (`config_used.json` ne conservait que la recette brute `split_method`/`train_ratio`/
`split_date`, jamais la borne réellement calculée). `None` si train/test désactivé ou pour tout
ancien `meta.json` chargé tel quel (jamais migré rétroactivement).

## Conséquences

- **Changement scientifique attendu, pas une régression** : les métriques TRAIN/TEST peuvent
  changer pour toute configuration utilisant le split — des barres auparavant perdues sont
  désormais évaluées.
- Restent inchangés : optimisation sans train/test, `opt_start_date`/`opt_end_date`/`max_rows`,
  nombre de combinaisons, hashes de reprise (params uniquement), répertoires de job, anciens
  artefacts (jamais réécrits).
- `optimizer.py::compute_split_dates()` DISCOVERED/OPEN devient corrigé par cette mission — statut
  de clôture non encore synchronisé dans `AI_HANDOFF.md`/la roadmap (différé après revue
  utilisateur, voir mission de clôture séparée).
- Dette WARMUP dynamique (`strategies/perfect_revolution_v1.py::WARMUP=130`) reste `OPEN`, non
  traitée ici. `AF-V-02` reste non commencé.
