# Epics et tickets — AlphaForge V2

> Voir `docs/INDEX.md` pour la navigation. Roadmap source de vérité : `MASTER_ROADMAP.md` (révisée,
> `AF-RM-01-QC` validée, 2026-08-15). Modèle de domaine source de vérité : `DOMAIN_MODEL.md`
> (révisé, `AF-DOM-01-QC` validé, 2026-08-14). Dépendances transversales : `DEPENDENCY_MAP.md`
> (non modifié). Risques : `RISK_REGISTER.md`. Décisions ouvertes : `DECISION_BACKLOG.md`.
>
> **Recalcul complet (2026-08-15, mission `AF-TICKETS-01`)** : ce document est désormais organisé
> par **tracks AlphaForge** (`AF-DATA`, `AF-R`, `AF-F`, `AF-V`, `AF-S`, `AF-EFAST`, `AF-EPREC`,
> `AF-D`, `AF-P`, `AF-U`, `AF-DSL`, `AF-O`, `AF-INFRA`), pas par les anciennes Phases 0-8. Les
> tickets `PH0-OCI-01`→`PH0-OCI-10` et `PH1-01`→`PH1-08` restent **préservés avec leurs IDs
> d'origine, non renumérotés, non dupliqués sous un nouvel ID `AF-INFRA-*`** — voir §"Tickets
> historiques préservés". Aucun ancien ID n'est réutilisé pour un nouveau ticket AlphaForge.
>
> **CHECKPOINT DATA FOUNDATION (2026-08-15)** : `AF-DATA-01`→`AF-DATA-04A` **DONE**,
> **`GATE DATA = PASS`** — voir §10 pour le verdict complet (preuves, garanties IMPLEMENTED/
> FUTURE) et §11-12 pour la frontière d'exécution actuelle (`AF-R-01`/`AF-V-01`/`AF-F-01` READY).

---

## 1. Verdict sur l'ancien `EPICS_AND_TICKETS.md`

L'ancienne organisation en Epics `E0`-`E8` calqués sur les Phases 0-8 linéaires est
**SUPERSEDED AS EXECUTION STRUCTURE** — elle ne reflète plus les dépendances réelles validées par
`AF-RM-01-QC` (le Data Center n'était pas un track autonome, l'UI était positionnée comme une
Phase tardive unique, Discovery et Portfolio suivaient l'ordre des Phases plutôt que leurs vraies
dépendances). **Aucun contenu utile ne disparaît** : chaque item `E0`-`E8`/`T-*` est retrouvable
dans le mapping §2 ci-dessous, soit comme ticket historique préservé (`PH0-*`/`PH1-*`, toujours
d'actualité, non superseded), soit re-dérivé en ticket `AF-*` avec un scope corrigé par les
dépendances réelles.

Deux sous-ensembles bien distincts de l'ancien fichier ont un sort différent :
- **`PH0-OCI-01`→`PH0-OCI-10` et `PH1-01`→`PH1-08`** (tickets précis, Phase 0/1) : **PAS
  superseded** — c'est le contenu réel du track `INFRA` (continu), toujours ouvert, toujours
  d'actualité, préservé **tel quel** ci-dessous (§"Tickets historiques préservés").
- **Les Epics `E2`-`E8` et leurs tickets macroscopiques `T-*`** (Phases 2 à 8) : **superseded**
  comme structure — leur contenu est re-dérivé dans les nouveaux tracks `AF-DATA`/`AF-R`/`AF-V`/
  `AF-F`/`AF-S`/`AF-EFAST`/`AF-D`/`AF-P`/`AF-U`/`AF-DSL`/`AF-O` ci-dessous, avec un scope corrigé
  par le graphe de dépendances de `MASTER_ROADMAP.md`. Voir mapping §2.

---

## 2. Mapping ancien → nouveau

| Ancien item | Statut | Nouveau Track/Ticket | Note |
|---|---|---|---|
| `E0` — Architecture, OCI, préparation | DONE (documentaire) | — | Contenu livré, voir `docs/` |
| `PH0-01` — Documents d'architecture | DONE | — | Livré ; voir "Tickets historiques préservés" |
| `PH0-OCI-01` — Validation Linux réelle | **DONE, clos définitivement** | — | `PH0-OCI-01-BUG` inclus ; jamais remis en travail restant |
| `E1` / `PH1-01`→`PH1-08` — Serveur de staging | **PRESERVED, non superseded** | `AF-INFRA` (mapping) | IDs et contenu inchangés, voir §"Tickets historiques préservés" |
| `PH0-OCI-02`→`PH0-OCI-10` | **PRESERVED, non superseded** | `AF-INFRA` (mapping) | IDs et contenu inchangés |
| `E2` — Industrialisation Data Center (`T-DC-1`→`T-DC-7`) | SUPERSEDED (re-dérivé) | `AF-DATA-*` | Scope corrigé : plusieurs briques (`BacktestManifest`, `_content_hash`) déjà existantes, pas "à créer" |
| `E3` — Fiabilité scientifique (`T-VAL-1`→`T-VAL-6`) | SUPERSEDED (re-dérivé) | `AF-V-*` | `T-VAL-1` (audit look-ahead) reste pertinent, repris en note dans `AF-V-01` |
| `E4` — Refonte UI/UX (`T-UI-*`) | SUPERSEDED (re-dérivé) | `AF-U-01` | Plus jamais une Phase tardive unique — tranches continues |
| `E5` — Multi-actifs/portefeuille (`T-MA-1`→`T-MA-3`) | SUPERSEDED (re-dérivé) | `AF-P-01` | Dépendance technique recalculée (`V` + 2 `StrategyDefinition`) |
| `E6` — Éditeur de stratégies (`T-DSL-1`→`T-DSL-3`) | SUPERSEDED (re-dérivé) | `AF-DSL-01` | Toujours `DECISION-PENDING`, ADR 0014 |
| `E7` — Options (`T-OPT-1`→`T-OPT-3`) | SUPERSEDED (re-dérivé) | `AF-O-01` | Isolation inchangée |
| `E8` — Durcissement/commercialisation (`T-HARD-1`→`T-HARD-2`) | SUPERSEDED (re-dérivé, **partiellement corrigé**) | Hors tracks (produit) + `AF-INFRA` | Sécurité d'exploitation/audit/backups/secrets **ne sont pas conditionnels** à la commercialisation — voir §9 |
| Registries/Knowledge Base (nouveau, absent de l'ancien fichier) | NOUVEAU | `AF-F-*` | N'existait dans aucun ancien epic — introduit par le Domain Model |
| Strategy Discovery (nouveau) | NOUVEAU | `AF-D-*` | Idem |
| Precision Engine Contract (nouveau) | NOUVEAU | `AF-EPREC-*` | Idem |
| Research Scope/SearchSpace (nouveau) | NOUVEAU | `AF-S-*`/`AF-EFAST-*` | Idem |
| Experiment/ResearchRun (nouveau) | NOUVEAU | `AF-R-*` | Idem |

---

## 3. Epics par track (remplace les Epics `E0`-`E8`)

| Track | Epic | Statut | Bloqué par |
|---|---|---|---|
| **AF-DATA** | Data Center — Provenance & Qualité (`DATA-FOUNDATION`) | **DONE — `GATE DATA = PASS`** (2026-08-15) | — |
| **AF-EPREC** | Precision Engine — Contract d'abord | **READY** (1er ticket, non commencé) | Aucun (Domain Model stabilisé) |
| **AF-R** | Reproducibility & Research Foundations | **READY** (débloqué, non commencé) | — (`GATE DATA` satisfait) |
| **AF-V** | Scientific Validation | **READY** (débloqué, non commencé) | — (`GATE DATA` satisfait) |
| **AF-F** | Strategy Knowledge / Registries | **READY** (débloqué, non commencé) | — (`GATE DATA` satisfait) |
| **AF-S** | Research Scope / SearchSpace | BLOCKED | `AF-F` (catalogue minimal réel) |
| **AF-EFAST** | Fast Backtest / Feature Computation | BLOCKED | `AF-F` (catalogue minimal réel) |
| **AF-D** | Strategy Discovery | BLOCKED | `GATE V` (entrée obligatoire) + `AF-F`/`AF-S`/`AF-EFAST` matures |
| **AF-P** | Portfolio | FUTURE | `GATE PORTFOLIO` |
| **AF-U** | UI / Strategy Laboratory | FUTURE (continu) | Stabilité des services backend, par tranche |
| **AF-DSL** | Strategy Authoring | DECISION-PENDING | ADR 0014 |
| **AF-O** | Options / Derivatives | FUTURE (isolé) | Aucune (jamais bloquant pour le spot) |
| **AF-INFRA** | OCI / Staging / Workers | PRESERVED, en cours | Voir tickets historiques préservés |

---

## 4. Tickets détaillés — Wave 1 (granularité maximale)

### AF-DATA-01 — Content-hash réel et stable pour le CSV local

**Status** : **DONE** (2026-08-15 — `market_data/content_hash.py`, 9 tests, `/code-review` passé)

**Track / Wave** : `AF-DATA` (`DATA-FOUNDATION`) / Wave 1.

**Why now** : c'est le seul verrou qui débloque `AF-R`, `AF-V`, `AF-F` via `GATE DATA` (voir
`MASTER_ROADMAP.md` §3-4). Aucune dépendance, réutilise du code déjà existant et testé.

**What to build** : une fonction pure calculant un hash sha256 stable du contenu du fichier CSV
local réellement utilisé (`nasdaq_3m.csv` aujourd'hui), sans jamais lire/écrire le fichier source
lui-même autrement qu'en lecture.

**Current evidence / existing code** : `market_data/eodhd/storage.py::_content_hash(payload:
bytes) -> str` existe déjà (sha256) mais est spécifique au chemin EODHD (raw/normalisé) — pas
branché sur le CSV local. `market_data/backtest_manifest.py` possède déjà le champ
`content_hash: Optional[str]` dans `BacktestManifest`, actuellement toujours `None` en pratique
(voir `AF-DATA-02`).

**Décision finale de seam (2026-08-15, corrige une analyse `codebase-design` antérieure de ce
même ticket qui recommandait une co-localisation dans `market_data/backtest_manifest.py`)** : le
seam retenu et implémenté est un **nouveau module dédié `market_data/content_hash.py`**, pas une
co-localisation dans `backtest_manifest.py`. Raison (ré-analyse `codebase-design`, mission
`AF-DATA-01` d'implémentation) : `content_hash()` est une primitive générique du domaine
`market_data` (identité d'un artefact fichier), tandis que `BacktestManifest` en est un
**consommateur**, pas son propriétaire — une co-localisation aurait créé une dépendance à
rebours. `content_hash.py` ne dépend d'aucun sous-système fournisseur (ni EODHD ni
`backtest_manifest`), reste réutilisable par toute future source locale. Une unification future
avec `eodhd/storage.py::_content_hash()` reste une amélioration possible, **hors scope** de ce
ticket.

**Dependencies** : aucune.

**Gate relationship** : contribue à `GATE DATA` (nécessaire mais pas suffisant seul — voir
`AF-DATA-02`).

**Files/modules concerned (réel)** : `market_data/content_hash.py` (nouveau module),
`tests/test_content_hash.py` (nouveaux tests, 9).

**In scope** : hash sha256 du contenu binaire du fichier ; déterminisme (même fichier → même
hash, deux exécutions consécutives) ; sensibilité au contenu (fichier modifié → hash différent,
test synthétique sur un fichier temporaire, jamais sur `nasdaq_3m.csv` lui-même).

**Out of scope** : ne matérialise **pas** encore une entité `DatasetVersion` cataloguée/
interrogeable au sens `DOMAIN_MODEL.md` §2 — seulement une preuve de provenance attachée à un run
(écart de vocabulaire confirmé par `domain-modeling`, 2026-08-15 : `BacktestManifest` reste un
constat par-run, pas encore un catalogue réutilisable entre runs — voir `AF-F`/DATA-ADVANCED pour
la matérialisation future). Pas de branchement sur EODHD (déjà couvert). Pas de refactor de
`_content_hash()` existant.

**Acceptance criteria** :
- [x] Une fonction pure `content_hash(path) -> str` retourne un sha256 hexadécimal du contenu du
      fichier.
- [x] Le même fichier hashé deux fois produit le même résultat.
- [x] Un fichier temporaire de test modifié produit un résultat différent.
- [x] Le fichier source n'est jamais modifié par la fonction (lecture seule).
- [x] `nasdaq_3m.csv` n'est ni modifié ni déplacé par les tests.

**Tests expected** : `/tdd` — tests unitaires purs, aucune dépendance à `job_store.py` ni à un job
réel (voir `AF-DATA-02` pour l'intégration).

**Non-regression / legacy compatibility** : sans objet à ce stade (fonction pure, non branchée).

**Risks** : lire un fichier volumineux entièrement en mémoire pour le hasher — acceptable à la
taille actuelle de `nasdaq_3m.csv` (mesurée dans `CURRENT_STATE.md`), à surveiller si la taille
change significativement (hors scope ici).

**Rollback** : fonction additive, aucun appelant existant — suppression triviale si besoin.

**Effort** : S. **Uncertainty** : low.

**Skills Claude Code recommended** : `tdd`.

**Manual authorization required** : aucune (code additif, pas encore branché).

---

### AF-DATA-02 — Propager le content_hash réel jusqu'à `data_manifest.json`

**Status** : **DONE** (2026-08-15 — `job_store.compute_source_content_hash`/`write_data_manifest`/
`finalize_job` étendus, `optimizer_process.py` câblé, HASH ONCE vérifié, `/code-review` passé)

**Track / Wave** : `AF-DATA` / Wave 1.

**Why now** : c'est le ticket qui rend `content_hash` réellement visible dans les artefacts d'un
nouveau run — sans lui, `AF-DATA-01` reste une fonction inutilisée.

**What to build** : `job_store.write_data_manifest()` (déjà branché dans
`finalize_job_outputs()`, déjà appelé pour chaque nouveau job) calcule et transmet un
`content_hash` réel (via `AF-DATA-01`), un `snapshot_id` (identité stable du fichier utilisé,
ex. nom + hash), et si disponibles `period_start`/`period_end` réels (déjà calculables depuis les
données chargées, voir `source_timeframe` déjà inféré par `market_data.resample
.infer_timeframe_from_series()`) à `build_backtest_manifest()`.

**Current evidence / existing code** : `job_store.py` lignes 444-478 — l'appel à
`build_backtest_manifest()` existe déjà et écrit déjà `data_manifest.json` pour chaque job, mais
sans passer `content_hash=`/`snapshot_id=`/`period_start=`/`period_end=` (restent `None`
aujourd'hui). C'est une modification d'un call-site existant, pas une nouvelle fonctionnalité de
bout en bout.

**Dependencies** : `AF-DATA-01` (fonction de hash disponible).

**Gate relationship** : condition principale de `GATE DATA`.

**Files/modules likely concerned** *(indicatif)* : `job_store.py::write_data_manifest()`,
`tests/test_job_store.py`.

**In scope** : propagation des champs déjà définis dans `BacktestManifest` ; aucun nouveau champ
sur la dataclass.

**Out of scope** : calendrier/DST, corporate actions, sync EODHD/Dukascopy (`DATA-ADVANCED`,
track continu séparé — voir `MASTER_ROADMAP.md`).

**Acceptance criteria** :
- [x] Un nouveau job sur `nasdaq_3m.csv` produit un `data_manifest.json` avec `content_hash` non
      vide.
- [x] Deux jobs successifs sur le même fichier produisent le même `content_hash`.
- [x] `snapshot_id` identifie le fichier utilisé de façon stable (finalisé par `AF-DATA-04A`, voir
      plus bas — absent de la portée initiale de ce ticket, ajouté après l'audit `GATE DATA`).
- [x] Aucune régression sur les artefacts historiques déjà produits par `finalize_job()`
      (`write_metrics`, `write_best_strategies`, `write_report_html`, `write_logs`,
      `write_archive` — 5 fonctions productrices des 7 fichiers de `ARCHIVE_SOURCE_FILES`).

**Tests expected** : `/tdd` — extension de `tests/test_job_store.py::test_write_data_manifest_
creates_a_valid_manifest` pour vérifier un `content_hash` réel non vide.

**Non-regression / legacy compatibility** : `write_data_manifest()` garde son comportement
`try/except` actuel (best-effort, jamais bloquant pour le job) — voir `AF-DATA-03` pour le test
explicite de compatibilité legacy.

**Risks** : ralentir la finalisation du job si le hash est recalculé à chaque appel plutôt que mis
en cache — à mesurer, mitigation possible (cache par chemin+mtime) si le coût est significatif,
**non anticipée sans mesure réelle**.

**Rollback** : `git diff job_store.py` localisé, comportement `try/except` déjà en place limite le
risque d'un job cassé.

**Effort** : S. **Uncertainty** : low.

**Skills Claude Code recommended** : `tdd`, `implement`.

**Manual authorization required** : autorisation explicite de modifier `job_store.py` (code
applicatif) — à demander au moment de l'implémentation, hors périmètre de cette mission
documentaire.

---

### AF-DATA-03 — Compatibilité legacy explicite (jobs sans provenance complète)

**Status** : **DONE** (2026-08-15 — 8 tests confirmant une garantie déjà acquise par construction,
aucune correction de code nécessaire, `/code-review` passé)

**Track / Wave** : `AF-DATA` / Wave 1.

**Why now** : condition explicite du principe "pas de backfill destructif" — doit être prouvée,
pas seulement supposée, avant de clore `GATE DATA`.

**What to build** : documentation + tests confirmant qu'un ancien job (sans `data_manifest.json`,
ou avec un `data_manifest.json` à `content_hash=None`) reste lisible et utilisable, interprété
explicitement comme **LEGACY / INCOMPLETE PROVENANCE**, sans jamais être réécrit rétroactivement.

**Current evidence / existing code** : cette garantie est **largement déjà acquise par
construction**, pas à construire depuis zéro : `save_backtest_manifest()` lève `FileExistsError`
si un manifeste existe déjà (jamais écrasé, capturée silencieusement dans
`write_data_manifest()`) ; `load_backtest_manifest()` retourne `None` de façon tolérante si le
fichier est absent, illisible ou invalide (jamais d'exception). Ce ticket **documente et teste**
cette garantie explicitement pour les besoins de `GATE DATA`, il ne l'implémente pas de zéro.

**Dependencies** : `AF-DATA-02` (pour comparer un job "nouveau" complet à un job "ancien"
incomplet).

**Gate relationship** : condition de `GATE DATA` ("job historique sans ces informations reste
lisible").

**Files/modules likely concerned** *(indicatif)* : `tests/test_job_store.py`,
`tests/test_backtest_manifest.py`, note dans `docs/architecture/DATA_ARCHITECTURE.md` (hors
périmètre de cette mission — à proposer séparément, pas modifié ici).

**In scope** : test explicite chargeant un job directory simulé sans `data_manifest.json` et
vérifiant qu'aucune fonction de lecture ne lève d'exception ; test confirmant qu'aucun ancien
`data_manifest.json`/`config_used.json`/`metrics.json`/`results.csv` n'est jamais réécrit par le
nouveau chemin.

**Out of scope** : construire un outil de migration/backfill rétroactif — **interdit** (voir
`MASTER_ROADMAP.md`, principe "pas de backfill destructif").

**Acceptance criteria** :
- [x] Un job directory sans `data_manifest.json` continue de fonctionner (affichage, reprise) sans
      exception.
- [x] `load_backtest_manifest()` sur un fichier absent/invalide retourne `None`, jamais
      d'exception (test explicite, pas seulement lu dans le code).
- [x] Aucun test ne modifie un artefact historique existant.
- [x] La distinction "LEGACY / INCOMPLETE PROVENANCE" vs "provenance complète" est vérifiable
      programmatiquement (ex. `content_hash is None`).

**Tests expected** : `/tdd`.

**Non-regression / legacy compatibility** : c'est l'objet même du ticket.

**Risks** : aucun risque de régression identifié — ticket principalement défensif/probatoire.

**Rollback** : sans objet (tests + documentation, aucun changement de comportement).

**Effort** : S. **Uncertainty** : low.

**Skills Claude Code recommended** : `tdd`.

**Manual authorization required** : aucune pour la documentation ; autorisation standard pour tout
test touchant potentiellement un vrai job directory (à exécuter sur des fixtures, jamais sur un
job historique réel).

---

### AF-DATA-04 — Quality Gate DATA

**Status** : **DONE (audit)** — verdict initial **`GATE DATA = NOT READY`** (2026-08-15), 3 gaps
concrets trouvés (`snapshot_id` jamais peuplé, `period_start`/`period_end` jamais peuplés,
fenêtre TOCTOU chargement→hachage non documentée/non mitigée). **Ne pas réécrire l'histoire** :
ce ticket n'est pas passé du premier coup — voir `AF-DATA-04A` ci-dessous pour le correctif, puis
la revalidation réelle qui a mené à **`GATE DATA = PASS`** (2026-08-15, même journée).

**Track / Wave** : `AF-DATA` / Wave 1. **Ce ticket a établi le verdict initial de `GATE DATA` —
c'est `AF-DATA-04A` + la revalidation qui ont effectivement franchi le gate.**

**Why now** : `GATE DATA` débloque `AF-R`, `AF-V`, `AF-F` (voir `MASTER_ROADMAP.md` §4) — sans une
vérification explicite et testée, le gate ne serait qu'une déclaration non prouvée.

**What to build** : la suite de tests de non-régression/reproductibilité qui **prouve**
`GATE DATA`, plus la vérification explicite de non-régression sur Perfect Revolution.

**Gate relationship** — `GATE DATA` traduit en critères vérifiables (repris de
`MASTER_ROADMAP.md` §4 et affiné). **État au moment de l'audit initial (2026-08-15, verdict
NOT READY)** :
- [x] Pour un **nouveau** run scientifique : source réellement identifiée (`provider`,
      `instrument`).
- [ ] `snapshot_id` identifiable pour le dataset utilisé. **FAIL à l'audit** — jamais peuplé par
      `write_data_manifest()`. **Fermé par `AF-DATA-04A`.**
- [x] `content_hash` réel et non vide.
- [ ] `period_start`/`period_end` réels quand disponibles. **FAIL à l'audit** — jamais peuplés
      alors que trivialement disponibles depuis le DataFrame déjà chargé. **Fermé par
      `AF-DATA-04A`.**
- [x] `source_timeframe` réel (déjà inféré aujourd'hui, non régressé).
- [x] Provenance enregistrée dans `data_manifest.json`.
- [x] Mêmes données → même identité/hash (test de déterminisme, `AF-DATA-01`).
- [x] Modification des données → identité/hash différent (test synthétique, `AF-DATA-01`).
- [x] Job historique sans ces informations reste lisible (`AF-DATA-03`).
- [ ] **Perfect Revolution non régressée** : test planifié à l'audit, **pas exécuté** (mission
      documentaire). **Exécuté réellement lors de la revalidation post-`AF-DATA-04A`** (voir
      ci-dessous) : 114 trades, stats strictement identiques entre calcul direct et pipeline job,
      cohérent avec la référence historique `PH0-OCI-01`. ✅

**Gap supplémentaire trouvé et fermé** : fenêtre TOCTOU (chargement du DataFrame vs relecture pour
le hash) non documentée/non mitigée à l'audit — hors de la checklist formelle du ticket mais
identifiée comme risque réel par `/codebase-design`/`/code-review`/MCP Codex. Fermée par
`AF-DATA-04A` (contrôle de stabilité filesystem, pas un second hash).

**Explicitement hors scope de `GATE DATA` minimal** (per mission, ne pas sur-demander) : Dukascopy,
corporate actions complètes, calendriers DST/holidays avancés — ces éléments appartiennent à
`DATA-ADVANCED` (track continu), pas au gate minimal.

**Tests expected** :
- Suite pytest existante toujours verte après `AF-DATA-01/02/03` — **confirmé (546/546 puis
  571/571 puis 588/588 au fil des tickets)**.
- Un test dédié comparant, sur `NASDAQ Perfect Revolution V1.1` + `DEFAULT_PARAMS`, la sortie de
  `engine.run_backtest()` (trades/equity/stats) **avant et après** le branchement du
  `content_hash` réel — doit être **strictement identique**.
- **Exécuté réellement le 2026-08-15** (autorisation explicite séparée, après `AF-DATA-04A`) :
  1 000 000 lignes, **114 trades**, stats identiques valeur par valeur entre un calcul direct
  (`engine.load_data`+`run_backtest`) et le vrai job pipeline (`job_gate_data_validation`),
  cohérent avec la référence historique `PH0-OCI-01` (114 trades, 999 869 points d'equity, verdict
  Windows/OCI déjà IDENTIQUE). Résultat non versionné (voir `AI_HANDOFF.md` pour la trace de
  preuve), `results/job_gate_data_validation/` non commité (dossier de résultats, hors dépôt Git).

**Non-regression / legacy compatibility** : c'est l'objet même de ce ticket — confirmé, aucun
ancien job modifié (vérifié par `stat` avant/après sur un job pré-existant).

**Risks** : un couplage accidentel entre le calcul du hash et le chemin de calcul du moteur —
mitigé en gardant `AF-DATA-01`/`AF-DATA-02`/`AF-DATA-04A` strictement additifs (aucune
modification de `engine.py`, confirmé par `/code-review` et MCP Codex).

**Rollback** : sans objet (tests).

**Effort** : S. **Uncertainty** : low.

**Skills Claude Code recommended** : `tdd`, `code-review` (revue finale du gate).

**Manual authorization required** : backtest complet de non-régression — **autorisé et exécuté le
2026-08-15**, voir preuve ci-dessus.

---

### AF-DATA-04A — Finaliser l'identité du snapshot CSV, les bornes source et la cohérence load/hash

**Status** : **DONE** (2026-08-15 — ticket correctif minimal créé après le verdict `NOT READY`
d'`AF-DATA-04`, pas planifié à l'origine)

**Track / Wave** : `AF-DATA` / Wave 1.

**Why now** : fermer les 2 checkboxes manquantes de `GATE DATA` (`snapshot_id`,
`period_start`/`period_end`) + le risque TOCTOU trouvé en sus par l'audit, sans transformer
`AF-DATA-04` en gros ticket d'implémentation (principe explicite : gap trouvé → `NOT READY` → un
ticket correctif minimal séparé, pas une correction silencieuse dans le même ticket).

**What to build** :
- `snapshot_id = "local_csv:sha256:" + content_hash` (référence de snapshot content-addressed
  typée — **pas** un `DatasetVersion` catalogué, voir §11 hors-scope).
- `period_start`/`period_end` = bornes min/max de `df["time"]` du dataset source **complet**,
  avant tout filtrage `opt_start_date`/`opt_end_date`/`max_rows` (Track R), format ISO-8601 UTC
  explicite.
- Contrôle de stabilité source léger (`capture_source_signature`/`assert_source_signature_
  unchanged`, taille+`mtime_ns`, **pas** un second SHA-256) entre chargement du DataFrame et
  calcul du hash — lève `SourceMutatedDuringLoadError` (non capturée) si une mutation ordinaire
  est détectée, avant la phase de calcul lourd.

**Current evidence / existing code** : construit entièrement sur `AF-DATA-01`/`AF-DATA-02` déjà
en place — aucune nouvelle architecture, aucun catalogue.

**Dependencies** : `AF-DATA-04` (audit ayant révélé le gap).

**Gate relationship** : ferme les 2 checkboxes `GATE DATA` restées `FAIL` à l'audit + le risque
TOCTOU trouvé en sus.

**Files/modules concerned (réel)** : `job_store.py` (+167 : `build_local_csv_snapshot_id`,
`compute_source_period_bounds`, `capture_source_signature`, `assert_source_signature_unchanged`,
`SourceMutatedDuringLoadError`), `optimizer_process.py` (+45, câblage), `tests/test_job_store.py`
(+15 tests), `tests/test_data_manifest_e2e.py` (nouveau, 2 tests subprocess réels).

**Out of scope (respecté)** : `DatasetVersionRepository`/`DatasetCatalog`/PostgreSQL/migration
DB/snapshot physique automatique ; `ResearchRun`/`DatasetSplitPlan`/`HoldoutAccessEvent` (Track
R) ; second hash complet ; verrou OS.

**Acceptance criteria** :
- [x] `snapshot_id` réel, format exact `local_csv:sha256:<content_hash>`, écrit dans le manifeste.
- [x] `period_start`/`period_end` réels, bornes du dataset source complet, non altérés par les
      filtres Track R (prouvé par un test e2e dédié avec filtres actifs).
- [x] Contrôle de stabilité : un seul SHA-256 par run (`HASH ONCE` toujours respecté, test dédié),
      mutation détectée (seam déterministe, pas de course réelle) → `SourceMutatedDuringLoadError`.
- [x] Compatibilité legacy : les trois nouveaux champs restent `None` si non fournis, aucun ancien
      test cassé.
- [x] Test end-to-end permanent (subprocess réel, CSV synthétique) prouvant le vrai câblage, pas
      des valeurs injectées.

**Tests expected** : `/tdd` — 15 tests unitaires + 2 tests subprocess réels.

**Non-regression / legacy compatibility** : confirmée — 588/588 (571 + 17 nouveaux) après
implémentation.

**Risks** : Data Clump noté (`content_hash`/`snapshot_id`/`period_start`/`period_end`/
`source_timeframe` répétés dans 4 signatures, a franchi le seuil des 3 occurrences de Fowler) —
voir §13 "Tech debt" ci-dessous, **pas corrigé maintenant** (pas un risque bloquant).

**Rollback** : additif, `git diff` localisé à 4 fichiers.

**Effort** : M. **Uncertainty** : low (construit sur du code déjà validé).

**Skills Claude Code recommended** : `domain-modeling`, `codebase-design`, `tdd`, `implement`,
`code-review`.

**Manual authorization required** : aucune au-delà de celle déjà donnée pour ce ticket correctif.

---

*(Verdict final `GATE DATA` détaillé, garanties IMPLEMENTED/FUTURE, et tech debt : voir §10
"`GATE DATA` — récapitulatif" plus bas, mis à jour avec le verdict final.)*

---

### AF-EPREC-01 — Precision Engine Contract

**Status** : **READY**

**Track / Wave** : `AF-EPREC` / Wave 1 (parallèle, indépendant de `AF-DATA`).

**Why now** : seul prérequis = Domain Model stabilisé (`AF-DOM-01-QC`, déjà fait). Peut démarrer
le même jour qu'`AF-DATA-01`, sans coordination.

**What to build** : la spécification/interface (documentaire, architecture) du futur Precision
Engine — `ExecutionModel`/`Order`/`OrderType`/`Position`/`Fill` (`DOMAIN_MODEL.md` §10), incluant
les policies nommées (`commission_policy`/`slippage_policy`/`spread_policy`/`margin_policy`) déjà
actées comme **une seule** entité composite (pas 4 entités top-level).

**Current evidence / existing code** : `engine.py` reste **CURRENT REFERENCE ENGINE, IMPLEMENTED +
TESTED** — ce ticket ne le modifie pas, ne le renomme pas. C'est un travail de spécification pure.

**Dependencies** : aucune.

**Gate relationship** : ne contribue à aucun gate directement — prérequis de `AF-EPREC-02` et de
`GATE PRECISION` (Wave 4).

**In scope** : contrat d'interface complet (types, invariants, modes d'erreur, ordonnancement) —
document de spécification, pas de code.

**Out of scope** : toute implémentation (`AF-EPREC-02`+) ; tout renommage d'`engine.py`.

**Acceptance criteria** :
- [ ] Chaque concept `DOMAIN_MODEL.md` §10 a une définition d'interface précise (signature +
      invariants + modes d'erreur).
- [ ] Le contrat est explicitement comparable au comportement actuel d'`engine.py` (base du futur
      test de conformance, `GATE PRECISION`).
- [ ] Aucune implémentation livrée par ce ticket.

**Tests expected** : sans objet à ce stade (spécification).

**Non-regression / legacy compatibility** : `engine.py` non touché.

**Risks** : sur-spécifier avant d'avoir un second cas d'usage réel — mitigé en s'en tenant au
contrat déjà esquissé dans `DOMAIN_MODEL.md`, pas une nouvelle invention.

**Rollback** : sans objet (documentation).

**Effort** : M. **Uncertainty** : medium (prembattre un contrat sans second moteur réel pour le
challenger).

**Skills Claude Code recommended** : `codebase-design`, `domain-modeling`.

**Manual authorization required** : aucune (documentation).

---

## 5. Tickets — Wave 1 suite (granularité maximale/bonne, débloqués par `GATE DATA = PASS`)

### AF-R-01 — Experiment / ResearchRun — schéma minimal + stockage fichier

**Status** : **DONE** (2026-08-15, `research_run.py` — committé et poussé,
`90e3e29c4c994c4bb54e571240a4121d5d2b16ee`, voir "Track R Foundation = COMPLETE" ci-dessous §11)

**What to build** : structures `Experiment` (durable, `hypothesis` optionnel) et `ResearchRun`
(exécution concrète immuable), stockées en fichiers (job directory existant, pas une nouvelle base
de données) — **ne prétend pas que PostgreSQL est nécessaire** à cette première implémentation
(ADR 0007 reste `Proposed`, non tranchée).

**Dependencies** : `GATE DATA`.

**In scope** : schéma minimal, persistance fichier réutilisant le job directory déjà existant.

**Out of scope** : PostgreSQL, UI, `SearchSpace` (dérivé par `ResearchRun`, jamais stocké sur
`Experiment` — voir `DOMAIN_MODEL.md`/`AF-DOM-01-QC`).

**Acceptance criteria** :
- [ ] Un `ResearchRun` référence un `DatasetVersion` (via `content_hash`/`snapshot_id` d'`AF-DATA`)
      par identifiant, pas par copie de valeur.
- [ ] Le job directory historique reste inchangé pour les jobs qui n'utilisent pas encore ce
      schéma.

**Effort** : M. **Uncertainty** : medium. **Skills recommended** : `domain-modeling`, `tdd`.

### AF-R-02 — Capture git_sha / seed / version logicielle par run

**Status** : **DONE** (2026-08-15, `research_run.py` — committé et poussé,
`90e3e29c4c994c4bb54e571240a4121d5d2b16ee`)

**What to build** : chaque nouveau `ResearchRun` capture automatiquement le `git_sha` (réutilise
`market_data.backtest_manifest._current_git_commit()`, déjà existant), un `seed` explicite, et la
version logicielle (`engine_version`, déjà existant dans `BacktestManifest`).

**Dependencies** : `AF-R-01`.

**Effort** : S. **Uncertainty** : low. **Skills recommended** : `tdd`.

### AF-R-03 — DatasetSplitPlan / HoldoutAccessEvent — fondations

**Status** : **DONE** (2026-08-15, `dataset_split.py` — committé et poussé,
`90e3e29c4c994c4bb54e571240a4121d5d2b16ee`)

**What to build** : fondations du plan de partition (train/test/holdout) d'un `DatasetVersion`, et
de l'audit d'accès au holdout (`HoldoutAccessEvent` référence `research_run_id` +
`dataset_version_id` directement — voir `AF-DOM-01-QC`). Invariant : un holdout accédé ne peut
jamais être décrit "intouché" sans vérifier les événements.

**Dependencies** : `AF-R-01`, `AF-DATA-02` (identité réelle du dataset).

**Effort** : M. **Uncertainty** : medium (premier cas d'usage réel encore absent — garder minimal).
**Skills recommended** : `domain-modeling`, `tdd`.

**Livré réellement (revue corrective incluse)** : `DatasetSplitPlan` identifié par son propre
`split_plan_id` (pas par `dataset_version_id`/`dataset_snapshot_id`, qui reste un champ direct
obligatoire) — cardinalité 1 snapshot -> N plans, corrigée après une première erreur de
modélisation trouvée en revue (voir `DOMAIN_MODEL.md` §12). `HoldoutAccessEvent` référence
`split_plan_id` ET `dataset_snapshot_id` directement (jamais l'un à la place de l'autre).
`ResearchRun.split_plan_id` **non ajouté** — différé explicitement à `AF-V-01` (premier
consommateur réel d'un plan), pas un oubli.

---

### AF-V-01 — OOS / holdout intouché — première `ValidationRun` réelle

**Status** : **DONE (2026-08-23)** — `HoldoutAccessEvent=1`, `ValidationEvidence=1`,
`validation_run_id="af-v01-ig-demo-final-holdout-oos"`, `split_plan_id=
"af-v01-ig-demo-nasdaq-m3-2026-08"`. **Preuve FRESH EXTERNAL FINAL HOLDOUT** (IG démo, distincte de
la retrospective OOS evidence MT5 — voir `DOMAIN_MODEL.md` §12). Résultat : `n_trades=0`,
**performance-inconclusive** (pas un échec technique, voir `docs/adr/0017-*.md` "Note de clôture").
**`GATE V` reste NON passée** — voir `MASTER_ROADMAP.md` §4 (exige `OOS`+`WalkForward`+
`MonteCarlo`+`ParameterStability`, seul `OOS` existe et son résultat est inconclusif). Aucun
`ROBUST`/`CHAMPION` déclaré.

**Why now** : `V` ne dépend que de `DATA-FOUNDATION` + `CURRENT REFERENCE ENGINE` (déjà
implémenté) — **ne bloque pas** sur le futur Precision Engine (`AF-EPREC`).

**What to build** : première exécution réelle d'une validation Out-of-Sample sur
`CURRENT REFERENCE ENGINE` + Perfect Revolution, produisant une `ValidationEvidence` réelle.

**Current evidence / existing code** : `dataset_split.py`/`validation_run.py`/`validation_oos.py`
(implémentés, `AF-R-03`/`AF-V-01`) ; `docs/adr/0017-ig-demo-dataset-snapshot-identity-and-timezone-assumption.md`
(dataset IG, correction fuseau horaire, exécution réelle documentée en détail).

**Dependencies** : `GATE DATA`.

**Note historique reprise** : couvre l'intention de l'ancien `T-VAL-1` (audit look-ahead bias dans
`engine.py`/`on_bar()`) comme prérequis d'hygiène avant la première `ValidationRun` — à vérifier
en ouverture de ce ticket, pas un ticket séparé. **Limite trouvée en clôture, non corrigée ici**
(hors périmètre strict) : `engine.run_backtest()` calcule les indicateurs (EMA/ATR) uniquement sur
les bougies de la fenêtre filtrée, jamais sur `TRAIN` — biais de "cold start" plausible, documenté
dans l'ADR-0017, à traiter par un futur ticket dédié à `engine.py` si jugé nécessaire.

**Acceptance criteria** :
- [x] Une période holdout est définie et jamais utilisée pour ajuster quoi que ce soit avant le
      verdict final.
- [x] `ValidationEvidence` produite et lisible.

**Effort** : M. **Uncertainty** : medium. **Skills recommended** : `tdd`.

### AF-V-02 — Walk-Forward

**Status** : **READY** (`AF-V-01` terminé — débloqué mécaniquement, **non commencé**, `GATE V`
toujours ouverte). **Précédence architecturale recommandée, pas un blocage technique dur** :
`AF-V-06` (socle `ValidationSpecification`/`ValidationEvidence` typé) devrait être traité avant ce
ticket pour éviter de retyper une `ValidationEvidence` déjà produite en format `dict` — c'est
`AF-V-06` lui-même qui déclare cette recommandation (voir son entrée ci-dessous), ce n'est pas une
dépendance inventée ici. **Effort** : M. **Skills recommended** : `tdd`.

**What to build** : moteur walk-forward sur `CURRENT REFERENCE ENGINE`, `ValidationEvidence`
dédiée. **Zones consommées : non tranchées ici, décision de conception propre à ce ticket**
(correction 2026-09-12 — une version antérieure de cette entrée présumait à tort une exécution de
`TRAIN`/`FINAL_HOLDOUT`) : `TRAIN` reste la zone de recherche/ajustement selon le protocole
retenu ; les fenêtres out-of-sample répétées (folds) proviendront de `VALIDATION` et/ou
`DISCOVERY_OOS`, conformément à `DOMAIN_MODEL.md` §12 — le choix précis entre les deux, ou leur
usage combiné, appartient à la conception réelle d'`AF-V-02`, pas à cette réconciliation
documentaire. **`FINAL_HOLDOUT` garde son statut distinct de preuve terminale contrôlée** : son
accès reste exclusivement audité via `HoldoutAccessEvent` (même mécanisme que pour `AF-V-01`), et
il ne doit **jamais** être implicitement réutilisé comme fold ordinaire à travers un futur
Walk-Forward — toute évaluation qui le consulterait resterait un événement d'accès distinct et
délibéré, pas un mécanisme interne au protocole.

**Préconditions scientifiques à examiner avant exécution (réconciliation documentaire post-AF-V-01,
2026-09-12, corrigée le 2026-09-12 — documentées séparément, non corrigées par ce ticket, aucune
des deux prouvée comme ayant affecté `AF-V-01`)** :
- **Dette A — warmup/cold-start des indicateurs** : `engine.run_backtest()` filtre la fenêtre
  avant `strategy.prepare()` (`engine.py:87-98`) — les indicateurs (EMA/ATR) ne voient jamais les
  bougies qui précèdent la fenêtre exécutée. Documenté dans `AI_HANDOFF.md` §14 et
  `docs/adr/0017-*.md` ("Note de clôture").
- **Dette B — sémantique des frontières `SplitBoundary`, générique** : `SplitBoundary` déclare
  `[start, end)` (fin exclue), mais `engine.run_backtest(start_date=, end_date=)` filtre en
  réalité sur un intervalle **fermé** des deux côtés (`time_paris >= start_date` **et**
  `time_paris <= end_date`, jamais `< end_date`) — toute exécution de deux fenêtres temporelles
  adjacentes peut donc provoquer une double inclusion d'une barre située exactement à la frontière
  partagée (`a.end == b.start`). Documenté dans le docstring de `SplitBoundary`
  (`dataset_split.py`). **Ne concerne pas spécifiquement `TRAIN`/`FINAL_HOLDOUT`** — c'est une
  propriété générique de toute paire de fenêtres adjacentes qu'un futur protocole choisirait
  d'exécuter (zones réelles non tranchées ici, voir ci-dessus). Sans impact vérifié sur `AF-V-01`
  (une seule zone exécutée, aucune bougie réelle sur la frontière `2025-05-19T00:00:00+00:00`).
  **Dette distincte de la Dette A.**

### AF-V-03 — Monte-Carlo

**Status** : **READY** (`AF-V-01` terminé — débloqué mécaniquement, **non commencé**). Précédence
recommandée (pas un blocage dur) : `AF-V-06`, même motif que `AF-V-02` ci-dessus. **Effort** : M.
**Skills recommended** : `tdd`.

### AF-V-04 — Parameter Stability

**Status** : **READY** (`AF-V-01` terminé — débloqué mécaniquement, **non commencé**). Précédence
recommandée (pas un blocage dur) : `AF-V-06`, même motif que `AF-V-02` ci-dessus. **Effort** : M.
**Skills recommended** : `tdd`.

### AF-V-05 — Stress / Noise

**Status** : **READY** (`AF-V-01` terminé — débloqué mécaniquement, **non commencé**). Précédence
recommandée (pas un blocage dur) : `AF-V-06`, même motif que `AF-V-02` ci-dessus. **Rappel** : ce
type de validation n'est **pas** parmi les quatre exigés par `GATE V` (`OOS`+`WalkForward`+
`MonteCarlo`+`ParameterStability`, voir `MASTER_ROADMAP.md` §4) — priorité plus faible que
`AF-V-02`→`AF-V-04`. **Effort** : M. **Uncertainty** : medium (protocole exact encore à affiner).
**Skills recommended** : `tdd`, `domain-modeling`.

### AF-V-06 — `ValidationSpecification` / `ValidationEvidence` typés par `validation_type`

**Status** : **READY** (`AF-V-01` terminé — débloqué mécaniquement, **non commencé**).
**Séquencement architectural confirmé (réconciliation documentaire post-AF-V-01, 2026-09-12)** :
ce ticket est le socle commun explicitement désigné par `AF-V-02`→`AF-V-05` (chacun produit une
`ValidationEvidence` qui a besoin de cette structure typée) — le traiter en premier évite de
retyper une évidence déjà produite en format `dict` par un ticket antérieur. **Ce n'est pas une
dépendance technique bloquante déclarée sur `AF-V-02`→`AF-V-05`** (chacun reste exécutable sans
`AF-V-06`), seulement un ordre recommandé par la source elle-même pour éviter du retravail.

**What to build** : structure typée par type de validation (pas un dict opaque) — correction déjà
actée par `AF-DOM-01-QC`. Sert de socle commun à `AF-V-02`→`AF-V-05`.

**Dependencies** : `AF-V-01`.

**Effort** : S. **Uncertainty** : low. **Skills recommended** : `domain-modeling`, `tdd`.

### AF-V-07 — `ValidationPolicyVersion` (fondation)

**Status** : BLOCKED (`AF-V-06`) — inchangé, `AF-V-06` n'est que `READY`, pas encore `DONE`.
**Effort** : S. **Uncertainty** : medium (frontières de "Champion" encore `OPEN QUESTION`, voir
`DOMAIN_MODEL.md` §13). **Skills recommended** : `domain-modeling`.

---

### AF-F-01 — Knowledge Base foundation

**Status** : **READY** (`GATE DATA = PASS`, 2026-08-15 — débloqué, non commencé)

**What to build** : premiers fichiers de référence déclaratifs (`KnowledgeSource`/`Reference`,
Git-file-based, immuables — décision `PostgreSQL`/`CatalogEntry` reste `PROPOSED`, ADR 0007 non
tranchée, **ne pas la présumer nécessaire ici**).

**Dependencies** : `GATE DATA`. **Effort** : M. **Uncertainty** : medium. **Skills recommended** :
`domain-modeling`.

### AF-F-02 — Strategy Registry additif

**Status** : BLOCKED (`AF-F-01`)

**What to build** : couche d'introspection additive sur les stratégies existantes.

**IMPORTANT — contrainte non négociable** : le premier Strategy Registry **ne remplace pas**
`glob strategies/*.py` — la découverte Python actuelle continue de fonctionner à l'identique.
Perfect Revolution (`perfect_revolution_v1.py`) reste inchangée. Le Registry est un
adapter/introspection additif par-dessus, jamais un remplacement destructif.

**Dependencies** : `AF-F-01`.

**Acceptance criteria** :
- [ ] `glob strategies/*.py` continue de fonctionner sans modification après ce ticket.
- [ ] `perfect_revolution_v1.py` non modifié.
- [ ] Le Registry expose les stratégies existantes en plus du mécanisme glob, pas à sa place.

**Effort** : M. **Uncertainty** : medium. **Skills recommended** : `codebase-design`, `tdd`.

### AF-F-03 — Indicator Registry

**Status** : BLOCKED (`AF-F-02`). **Effort** : M. **Skills recommended** : `domain-modeling`.

### AF-F-04 — Feature Registry

**Status** : BLOCKED (`AF-F-03`). **Effort** : M. **Skills recommended** : `domain-modeling`.

### AF-F-05 — Signal Registry

**Status** : BLOCKED (`AF-F-04`). **Effort** : M. **Skills recommended** : `domain-modeling`.

---

## 6. Tickets — Wave 2 (granularité moyenne)

### AF-S-01 — `ResearchScope` → `SearchSpace` (modèle + taille théorique)

**Status** : BLOCKED (`AF-F` — catalogue minimal réel)

**What to build** : modèle `ResearchScope` (dual-sémantique `timeframes`, voir `AF-DOM-01-QC`) et
calcul de taille théorique de `SearchSpace` — **pas d'exécution réelle** à ce stade.

**Effort** : M. **Uncertainty** : medium. **Skills recommended** : `domain-modeling`.

### AF-S-02 — Résolution de compatibilité (candidats valides)

**Status** : BLOCKED (`AF-S-01`). **Effort** : M. **Uncertainty** : medium.

### AF-EFAST-01 — Cache versionné + benchmark first

**Status** : BLOCKED (`AF-F` — catalogue minimal réel)

**What to build** : cache versionné par `dataset content_hash + FeatureVersion + paramètres +
timeframe + version logicielle`, **benchmark avant tout choix technique**.

**IMPORTANT** : **ne décide pas prématurément** Polars/Numba ni l'architecture de cache finale —
ce ticket produit des mesures, pas une décision d'implémentation figée. Réutilise le protocole
déjà défini dans `BENCHMARK_PLAN.md`.

**Effort** : M. **Uncertainty** : high (dépend des résultats du benchmark). **Skills
recommended** : aucun skill Claude Code spécifique — mesure d'abord.

---

## 7. Tickets — Waves suivantes (macro / placeholder explicite)

> Les tickets ci-dessous sont volontairement macroscopiques : l'architecture de leurs sous-domaines
> n'est pas encore assez décidée pour un découpage précis sans inventer de fausse précision.

### AF-D-01 — Random Baseline (exigence explicite)

**Status** : BLOCKED (`GATE V`, `AF-F`/`AF-S`/`AF-EFAST` matures)

**What to build** : `Random Baseline`, toujours produite en premier avant toute méthode
sophistiquée, comparée à budget de calcul comparable.

**Critère explicite** (repris de `MASTER_ROADMAP.md` §4, `GATE D` reformulée) : la valeur d'une
méthode sophistiquée **n'est pas** "doit toujours battre Random sur chaque run" — elle peut se
démontrer par qualité, efficacité de recherche, couverture, stabilité des paramètres, ou coût de
recherche, individuellement ou combinés.

**Effort** : M. **Uncertainty** : medium. **Skills recommended** : `tdd`, `domain-modeling`.

### AF-D-02 — Combination Engine progressif (macro)

**Status** : FUTURE (bloqué par `AF-D-01`). Paires → triplets → recherche plus sophistiquée.
Représentation déclarative interne, **sans DSL utilisateur** (voir `AF-DSL`, non-prérequis).

### AF-D-03 — Méthodes sophistiquées (macro)

**Status** : FUTURE. Evolutionary/Genetic, Bayesian, CMA-ES — chacune comparée à `AF-D-01` à
budget comparable, gatée par `GATE D`.

### AF-D-04 — Genetic Programming

**Status** : **FUTURE explicite, uniquement si justifié par un besoin réel** — jamais un
prérequis des premiers prototypes `AF-D-01`→`AF-D-03`.

**Anti-overfitting (rappel, rattaché à `AF-D`/`AF-R`, pas un epic séparé)** : FOUNDATION (holdout
intouché + `AF-R-03`, nested validation, comptage de candidats, `AF-D-01`, stabilité des
paramètres, contrôle de complexité) s'applique dès `AF-D-01`. RECOMMENDED (DSR, PBO/CSCV, contrôle
de fausses découvertes, sensibilité régime/marché croisé) seulement au-delà de quelques centaines
de candidats — **ne bloque pas les premiers travaux `AF-D`.**

### AF-P-01 — Portfolio (macro epic)

**Status** : FUTURE (`GATE PORTFOLIO`)

**Dépendance technique** (réelle) : `AF-V` + au moins 2 `StrategyDefinition` validées — peuvent
venir d'`AF-F` seul (hand-authored), **pas artificiellement dépendant de `AF-D`**.
**Réalité produit** : `AF-D` sera la source principale de candidats à l'échelle en pratique — les
deux sont montrées séparément, jamais confondues (voir `MASTER_ROADMAP.md` §3).

Prévu à terme (non détaillé en tickets, macro) : capital partagé, allocation, exposition,
corrélation, concentration, drawdown, validation de portefeuille, `StrategyHealth` (FUTURE),
`MarketRegime`. **Aucun de ces éléments n'est READY maintenant.**

### AF-U-01 — UI / Strategy Laboratory (macro epic, tranches verticales continues)

**Status** : FUTURE (continu, déclenché par service backend stabilisé — **jamais** une refonte
générale permanente)

Tranches futures indicatives : Research Scope UI, aperçu `SearchSpace`, Laboratoire de stratégies,
Validation, Résultats, Champions, Portfolio, Administration. Chaque tranche est un ticket propre,
créé **au moment où** le service backend correspondant est stable — pas avant, pas en avance de
phase. Streamlit reste interface uniquement, jamais moteur d'exécution.

### AF-DSL-01 — Strategy Authoring (macro epic)

**Status** : **DECISION-PENDING** (ADR 0014)

Le DSL utilisateur ne bloque ni les Registries (`AF-F`), ni `StrategyDefinition` interne, ni
`AF-D`. Tout ticket d'implémentation DSL reste `BLOCKED`/`DECISION-PENDING` tant qu'ADR 0014 n'est
pas tranchée.

### AF-O-01 — Options / Derivatives (macro epic, isolé)

**Status** : FUTURE (isolé, jamais bloquant)

IG démo lecture seule uniquement à ce stade. Ne bloque jamais spot/`AF-D`/`AF-P`. ADR 0011 reste
`Proposed`.

---

## 8. `AF-INFRA` — epic de rattachement (pas de duplication)

`AF-INFRA` ne crée **aucun** nouveau ticket dupliquant `PH0-OCI-02`→`PH0-OCI-10` ou
`PH1-01`→`PH1-08` — ces tickets **existants** couvrent déjà Docker Compose, stockage, secrets,
arrêt automatique, protections budgétaires, HTTPS, sauvegardes, observabilité (voir
§"Tickets historiques préservés" ci-dessous). `AF-INFRA` sert uniquement de point de rattachement/
mapping pour de futurs tickets non encore représentés (aucun identifié à ce stade).

ADR 0006 (RQ vs Celery) reste `Decision pending`. ADR 0007 (PostgreSQL) reste `Proposed`.

---

## 9. Sécurité / Observabilité / Backup — non conditionnels à la commercialisation

**Correction explicite de l'ancien regroupement (`AF-TICKETS-01`)** : secrets (`PH0-OCI-05`,
`PH1-05`), sauvegarde/restauration (`PH1-07`), observabilité (`PH1-08`), protections budgétaires
(`PH0-OCI-07`), arrêt automatique (`PH0-OCI-06`), audit technique — **ne sont pas conditionnels à
une hypothétique commercialisation**. Ils vivent sous `AF-INFRA`/durcissement et sont déjà couverts
par des tickets `PH0-OCI-*`/`PH1-*` existants, requis bien avant toute décision produit.
Seuls restent conditionnels à une décision explicite de commercialisation : authentification
multi-utilisateur avancée, rôles commerciaux, facturation (`T-HARD-1`/`T-HARD-2`, macro, hors
tracks).

---

## 10. `GATE DATA` — verdict final : **PASS** (2026-08-15)

Liste complète des critères vérifiables dans `AF-DATA-01`(hash), `AF-DATA-02`(propagation),
`AF-DATA-03`(compatibilité legacy), `AF-DATA-04`(gate, audit initial) et `AF-DATA-04A`(correctif).
Aucun critère de `GATE DATA` n'est laissé à l'état de prose non vérifiable.

**`GATE DATA = PASS`**, confirmé par 10/10 critères de la checklist `AF-DATA-04`, `/code-review`
(2 axes) et MCP Codex (revue indépendante, verdict atteint séparément). **Séquence réelle, non
réécrite** : `AF-DATA-04` (audit) → **`NOT READY`** (2 gaps + 1 risque TOCTOU trouvés) →
`AF-DATA-04A` (correctif minimal) → revalidation réelle (Perfect Revolution, 114 trades,
1 000 000 lignes) → **`PASS`**. Ce gate n'a pas été franchi du premier coup.

**IMPLEMENTED (Track DATA, CSV local)** : identité de l'artefact source (SHA-256 réel, streamé,
`market_data/content_hash.py`) ; référence de snapshot content-addressed typée (`snapshot_id =
"local_csv:sha256:" + content_hash`) ; bornes du dataset source complet (`period_start`/
`period_end`, ISO-8601 UTC) ; `source_timeframe` honnête ; manifeste immuable par job
(`data_manifest.json`) ; compatibilité legacy prouvée (READ OLD / WRITE NEW, aucun backfill) ;
contrôle metadata (taille+`mtime_ns`) contre une mutation ordinaire pendant la fenêtre
chargement→hachage ; non-régression Perfect Revolution prouvée en conditions réelles (114 trades,
stats identiques, cohérent avec la référence historique `PH0-OCI-01`).

**FUTURE (ne pas prétendre déjà livré)** : catalogue `DatasetVersion` persistant/interrogeable
(PostgreSQL ou autre, ADR 0007 toujours `Proposed`) ; copie physique content-addressed
automatique ; verrouillage de fichier ; protection contre un acteur malveillant falsifiant
taille+horodatage simultanément au contenu ; `DATA-ADVANCED` (Dukascopy, corporate actions
complètes, calendriers DST/holidays avancés, sync incrémental) ; sélection/lignes effectivement
consommées après filtrage (`opt_start_date`/`opt_end_date`/`max_rows`, `DatasetSplitPlan`,
`HoldoutAccessEvent`, `ResearchRun`) — **Track R**, jamais Track DATA (frontière validée,
`GATE DATA` ne dépend d'aucun de ces éléments).

**Tech debt notée, non bloquante** : le groupe de paramètres `(content_hash, snapshot_id,
period_start, period_end, source_timeframe)` apparaît désormais identique dans 4 signatures
(`optimizer_process.py`, `finalize_job`, `write_data_manifest`, `build_backtest_manifest`) — a
franchi le seuil des "3 occurrences" de Fowler, candidat sérieux pour un futur objet de valeur
(ex. `SourceProvenance`). Pas un ticket, pas de code maintenant — à considérer si un 6e champ de
provenance s'ajoute un jour.

---

## 11. CURRENT EXECUTION QUEUE — WAVE 1

**TERMINÉ (2026-08-15)** — `DATA-FOUNDATION` complète, `GATE DATA = PASS` :
1. ✅ `AF-DATA-01` — content_hash réel et stable pour le CSV local.
2. ✅ `AF-DATA-02` — propagation dans `data_manifest.json`.
3. ✅ `AF-DATA-03` — compatibilité legacy (documentation + tests).
4. ✅ `AF-DATA-04` — Quality Gate DATA (audit → `NOT READY`).
5. ✅ `AF-DATA-04A` — correctif minimal (`snapshot_id`/bornes source/contrôle de stabilité).
6. ✅ Revalidation réelle (Perfect Revolution, 114 trades) → **`GATE DATA = PASS`**.

**TRACK R FOUNDATION = COMPLETE (2026-08-15, committé et poussé —
`90e3e29c4c994c4bb54e571240a4121d5d2b16ee`, `origin/master`)** — pas un `GATE R` officiel (ce nom
n'existe pas dans la roadmap, voir §12 historique ci-dessous) :
1. ✅ `AF-R-01` — Experiment/ResearchRun, schéma minimal + stockage fichier.
2. ✅ `AF-R-02` — capture `git_sha`/`seed`/`engine_version`.
3. ✅ `AF-R-03` — DatasetSplitPlan/HoldoutAccessEvent, fondations (cardinalité corrigée en revue).

**AF-V-01 = DONE (2026-08-23, committé et poussé — checkpoint
`a1cde845f1e73c6443abbf3babfe7525112bbf8b`, `origin/master`)** — première `ValidationRun` réelle
sur un `DatasetSplitPlan` IG démo (fresh external final holdout, distincte de la retrospective OOS
evidence MT5) : `n_trades=0`, performance-inconclusive, `GATE V` toujours ouverte — voir l'entrée
du ticket ci-dessus et `DOMAIN_MODEL.md` §12 pour le détail complet.

**READY NOW** (débloqués — voir note de précédence recommandée `AF-V-06` ci-dessous, distincte
d'un blocage technique ; réconciliation documentaire post-AF-V-01, 2026-09-12) :
- `AF-V-06` — socle `ValidationSpecification`/`ValidationEvidence` typé, débloqué par `AF-V-01`.
  Non commencé. **Précédence architecturale recommandée sur `AF-V-02`→`AF-V-05`** — voir le
  ticket `AF-V-06` (§5) : ce n'est pas une dépendance technique dure, seulement un ordre qui évite
  du retypage a posteriori.
- `AF-V-02` — Walk-Forward, débloqué par `AF-V-01`. Non commencé. Deux préconditions scientifiques
  distinctes à examiner avant exécution (warmup/cold-start ; sémantique `SplitBoundary`) —
  documentées dans le ticket (§5), non corrigées.
- `AF-V-03`/`AF-V-04`/`AF-V-05` — également débloqués par `AF-V-01` (dépendance déclarée
  satisfaite, corrigé depuis l'ancien statut `BLOCKED` affiché ici), non commencés — voir §5 pour
  le détail et la même précédence recommandée `AF-V-06`.
- `AF-F-01` — Knowledge Base foundation. Non commencé.
- `AF-EPREC-01` — Precision Engine Contract (déjà `READY` depuis le début, indépendant de
  `AF-DATA` — à vérifier s'il a déjà été traité séparément avant de le redémarrer).

Cet ordre reste dérivé directement des dépendances déclarées et des recommandations déjà présentes
dans les tickets sources — `AF-V-06`/`AF-V-02`→`AF-V-05`/`AF-F-01`/`AF-EPREC-01` ne forment *pas*
un unique chemin séquentiel imposé par le graphe, à l'exception de la précédence `AF-V-06` →
`AF-V-02`→`AF-V-05` explicitement recommandée par la source elle-même (ticket `AF-V-06`).

---

## 12. Prochaine action unique

**Historique (avant 2026-08-15)** : cette section recommandait `AF-R-01` en premier parmi trois
choix parallèles (`AF-R-01`/`AF-V-01`/`AF-F-01`, tous `READY` sans dépendance croisée). C'est
désormais fait — voir §11, Track R Foundation complète.

**Historique (avant 2026-08-23)** : cette section recommandait `AF-V-01` en premier parmi
`AF-V-01`/`AF-F-01`, tous deux `READY` sans dépendance croisée. C'est désormais fait — voir §11,
`AF-V-01 = DONE`. La question laissée `FUTURE` par `AF-R-03` ("comment un `ResearchRun`
référence-t-il le `DatasetSplitPlan` qu'il a utilisé ?") a été tranchée avec ce cas d'usage réel
(`ValidationRun.split_plan_id` direct, voir `validation_run.py`).

**Historique (avant 2026-09-12, synchronisation documentaire post-AF-V-01)** : cette section ne
comparait que `AF-V-02` et `AF-F-01`. Réconciliation effectuée (voir §5) : `AF-V-03`, `AF-V-04`,
`AF-V-05` et `AF-V-06` sont eux aussi mécaniquement `READY` (dépendance déclarée `AF-V-01`
satisfaite) — ce n'était pas encore reflété ici. `AF-V-06` porte en plus une précédence
architecturale **recommandée par le ticket source lui-même** ("devrait en réalité précéder
`AF-V-02`→`AF-V-05`") — rendue explicite dans ce document, pas inventée.

**État actuel** : au sein du track `V`, `AF-V-06` est la sous-priorité recommandée par les sources
elles-mêmes avant `AF-V-02`→`AF-V-05` (socle typé, évite un retypage a posteriori de
`ValidationEvidence`) — **précédence architecturale conseillée, pas une dépendance technique
dure**. Entre tracks, `AF-V-06` et `AF-F-01` restent `READY` sans dépendance croisée entre eux —
aucun gagnant unique n'est imposé par le graphe à ce niveau. `GATE V` exige toujours
`OOS`+`WalkForward`+`MonteCarlo`+`ParameterStability`, et le résultat `OOS` obtenu (`n_trades=0`)
reste performance-inconclusive — une décision produit explicite reste nécessaire avant de lancer
tout travail d'**exécution** de validation (`AF-V-02`→`AF-V-05`), **pas** avant `AF-V-06` lui-même
(travail de structuration typée, pas une nouvelle exécution scientifique). `AF-F-01` reste un choix
tout aussi valide selon la priorité produit du moment.

**Important** : cette recommandation n'autorise rien de nouveau — `AF-V-06` (ou tout autre ticket
de ce track) doit être explicitement autorisé par l'utilisateur avant tout travail, comme chaque
ticket précédent.

---

## 13. Décisions bloquantes encore ouvertes

- ADR 0006 (RQ vs Celery) — `Decision pending`, bloque uniquement `AF-INFRA`/workers distribués.
- ADR 0007 (PostgreSQL) — `Proposed`, ne bloque **pas** `AF-R-01`/`AF-F-01` (stockage fichier
  suffisant pour la première implémentation).
- ADR 0014 (DSL) — `Decision pending`, bloque `AF-DSL-01`+ uniquement, jamais `AF-F`/`AF-D`.
- `GATE PRECISION` comme condition supplémentaire de `GATE CHAMPION` — `PROPOSED TARGET`, non
  tranché (`MASTER_ROADMAP.md` §4).
- Frontières exactes de "Champion" — `OPEN QUESTION` (`DOMAIN_MODEL.md` §13), affecte `AF-V-07`.
- Toutes les décisions de `docs/roadmap/DECISION_BACKLOG.md` (non modifié) restent valides.
- **Rappel statuts ADR réels (vérifiés au 2026-08-15)** : seul **ADR 0015 est `Accepted`**. Aucun
  autre ADR référencé dans ce document n'est présenté comme `Accepted`.

---

## 14. Tickets historiques préservés

> Contenu **identique** à l'ancien `EPICS_AND_TICKETS.md` — aucune modification, aucune
> renumérotation. `PH0-OCI-01` et `PH0-OCI-01-BUG` sont **clos définitivement** (voir statuts
> ci-dessous) et n'apparaissent plus jamais comme travail restant. `PH0-OCI-02`→`PH0-OCI-10` et
> `PH1-01`→`PH1-08` restent **ouverts**, non superseded — c'est le contenu réel du track `INFRA`
> continu.

### PH0-01 — Documents d'architecture et ADR de la Phase 0

**Statut** : DONE. Livré par les missions documentaires de ce dépôt (voir `docs/INDEX.md`).
Détail complet préservé dans l'historique Git de ce fichier (avant `AF-TICKETS-01`, 2026-08-15).

### PH0-OCI-01 — Valider la portabilité Linux en conditions réelles

**Statut : DÉFINITIVEMENT CLOS (2026-08-14)** — validation Linux réelle complète sur OCI (546/546
pytest, `lancer_app.sh` réel HTTP 200, backtest comparatif Windows/OCI verdict IDENTIQUE). Voir
`LINUX_PORTABILITY_REPORT.md` §15 pour le détail complet. **N'apparaît plus jamais comme travail
restant.** Détail complet des critères et de l'historique préservé dans l'historique Git de ce
fichier (avant `AF-TICKETS-01`).

### PH0-OCI-01-BUG — Reprise de job (`resume_run_id`) cassée en mode job-directory

**Statut : CLOS.** Bug trouvé pendant l'audit de portabilité, corrigé et testé
(`tests/test_job_resume.py`, 11/11, inclus dans les 546/546). Détail complet préservé dans
l'historique Git de ce fichier (avant `AF-TICKETS-01`).

### PH0-OCI-02 — Préparer un squelette Docker Compose local

**What to build** : un `docker-compose.yml` **local** (poste de développement, pas encore OCI)
démarrant l'interface Streamlit actuelle et une instance PostgreSQL vide, pour valider la
structure avant tout déploiement cloud.

**Blocked by** : PH0-OCI-01 (clos — ce ticket peut démarrer).

**Contexte** : [ADR 0009](../adr/0009-docker-compose-for-staging.md) (Docker Compose retenu),
[ADR 0007](../adr/0007-postgresql-for-metadata.md) (PostgreSQL). Ce squelette local est le point
de départ du squelette OCI de PH1-02 (portée staging), pas un doublon — PH0-OCI-02 valide la
structure sans dépendre d'une instance cloud.

- [ ] `docker-compose up` démarre l'interface en local, accessible sur `localhost`.
- [ ] Aucun secret dans l'image ni dans le dépôt (fichier `.env` local non versionné).

**Tests attendus** : l'interface actuelle (backtest simple) fonctionne à l'identique sur ce
squelette local.
**Risques** : sur-ingénierie prématurée si le squelette anticipe des services non encore décidés
(Redis, workers) — s'en tenir à interface + PostgreSQL pour ce ticket.
**Rollback** : sans objet (additif, n'affecte pas l'exécution locale existante).
**Estimation** : S.
**Skills recommandés** : `implement`, `code-review` (autorisation de modifier du code requise en
son temps — hors périmètre strict de cette mission de planification).
**Autorisations manuelles requises** : création des fichiers Docker — hors périmètre de cette
mission de planification, autorisation explicite requise en son temps.

### PH0-OCI-03 — Définir le benchmark reproductible (local puis OCI)

**What to build** : le protocole de benchmark de `docs/roadmap/BENCHMARK_PLAN.md` §1, instancié
en scripts/procédure reproductible exécutable d'abord en local (référence), puis identique sur
OCI.

**Blocked by** : PH0-OCI-02.

**Contexte** : reprend et précise l'ancien PH0-02 (remplacement acté avant `AF-RM-01`) — le
protocole lui-même (tailles de données, combinaisons, workers, mesures) est déjà défini dans
`BENCHMARK_PLAN.md` §1, ce ticket produit la procédure d'exécution reproductible, pas un nouveau
protocole.

- [ ] Le protocole s'exécute de bout en bout en local et produit les mesures attendues
      (temps, CPU, RAM, E/S) de façon reproductible (deux exécutions locales donnent des mesures
      cohérentes).

**Tests attendus** : deux exécutions locales consécutives du même scénario donnent des mesures
dans une marge de variance acceptable (à définir).
**Risques** : mesures faussées par d'autres charges sur la machine — isoler l'exécution.
**Rollback** : sans objet.
**Estimation** : M.
**Skills recommandés** : aucun skill Claude Code spécifique.
**Autorisations manuelles requises** : aucune pour la partie locale.

### PH0-OCI-04 — Définir le stockage persistant OCI

**What to build** : décision motivée Block Volume vs Object Storage par type de donnée (brut
EODHD, normalisé Parquet, résultats de jobs, sauvegardes PostgreSQL) — voir
`docs/roadmap/DECISION_BACKLOG.md`.

**Blocked by** : PH0-OCI-01 (clos).

**Contexte** : [ADR 0008](../adr/0008-market-data-storage-strategy.md) fixe déjà la stratégie
générale (raw immuable/normalisé Parquet/dérivé) ; ce ticket l'instancie spécifiquement sur les
primitives OCI (Block Volume pour l'accès fréquent, Object Storage pour l'archivage/sauvegarde
probablement — à confirmer par étude technique, pas encore tranché).

- [ ] Chaque type de donnée listé dans `DATA_ARCHITECTURE.md` a une primitive OCI assignée
      (Block Volume ou Object Storage), documentée.

**Tests attendus** : sans objet (décision documentée).
**Risques** : mauvais choix initial coûteux à migrer — mitigé en documentant explicitement la
réversibilité de chaque choix.
**Rollback** : sans objet.
**Estimation** : S.
**Skills recommandés** : `WebSearch`/`WebFetch` (documentation officielle Oracle).
**Autorisations manuelles requises** : aucune (décision documentée, pas de ressource créée).
**Décision liée** : `DECISION_BACKLOG.md` — "Block Volume ou Object Storage par type de donnée".

### PH0-OCI-05 — Définir les secrets et permissions OCI

**What to build** : mécanisme de gestion des secrets sur OCI (variables d'environnement injectées
au démarrage, ou OCI Vault) et permissions minimales du compte de service utilisé par
l'application.

**Blocked by** : PH0-OCI-01 (clos).

**Contexte** : `docs/architecture/SECURITY_AND_OPERATIONS.md` §1-2 — règles déjà respectées en
local pour EODHD/IG, à étendre à OCI (clé API OCI elle-même, secrets applicatifs).

- [ ] Aucun secret OCI ni applicatif dans le dépôt ou dans une image Docker.
- [ ] Le compte/rôle OCI utilisé a des permissions minimales (pas de rôle administrateur complet
      pour l'application).

**Tests attendus** : vérification manuelle qu'aucun secret n'apparaît dans les logs/erreurs.
**Risques** : voir `RISK_REGISTER.md` — "Fuite de secrets".
**Rollback** : sans objet (mesure de sécurité additive).
**Estimation** : S.
**Skills recommandés** : `code-review` (axe sécurité).
**Autorisations manuelles requises** : création d'un compte/rôle OCI de service — autorisation
explicite requise.

### PH0-OCI-06 — Définir l'arrêt automatique

**What to build** : mécanisme technique d'arrêt automatique après inactivité et d'arrêt forcé
après durée maximale, indépendant des alertes budgétaires (voir
`SECURITY_AND_OPERATIONS.md` §7 — "principe non négociable").

**Blocked by** : PH0-OCI-01 (clos).

**Contexte** : cycle à la demande décrit dans `docs/architecture/COMPUTE_AND_JOBS.md` §6, étape
10. Ce ticket définit **comment** (API OCI, script planifié, autre), sans encore l'implémenter.

- [ ] Mécanisme documenté vérifiant l'absence de travail en file/en cours avant d'arrêter une
      instance.
- [ ] Mécanisme de secours (arrêt forcé après durée maximale) indépendant du premier.

**Tests attendus** : sans objet à ce stade (conception, pas implémentation).
**Risques** : arrêt déclenché à tort pendant un job encore utile — voir mitigation dans
`COMPUTE_AND_JOBS.md` §6.
**Rollback** : sans objet.
**Estimation** : M.
**Skills recommandés** : `codebase-design`.
**Autorisations manuelles requises** : aucune pour la conception.
**Décision liée** : `DECISION_BACKLOG.md` — "Mécanisme exact de démarrage/arrêt des workers OCI".

### PH0-OCI-07 — Définir les protections budgétaires

**What to build** : estimation de coût avant campagne, quotas (workers max, vCPU max, durée max
de job), alertes budgétaires, journal des heures de calcul, tableau de consommation, confirmation
utilisateur avant opération coûteuse, procédure d'arrêt d'urgence — liste complète dans
`SECURITY_AND_OPERATIONS.md` §7.

**Blocked by** : PH0-OCI-06 (l'arrêt automatique est le mécanisme technique complémentaire, pas
un substitut).

**Contexte** : principe explicite de l'utilisateur — "les alertes budgétaires ne doivent pas être
considérées comme l'unique protection".

- [ ] Chacune des 12 exigences de `SECURITY_AND_OPERATIONS.md` §7 a un mécanisme défini (pas
      nécessairement implémenté).

**Tests attendus** : sans objet à ce stade (conception).
**Risques** : facture imprévue si ce ticket n'est pas terminé avant PH0-OCI-09 (benchmark OCI
réel) — **dépendance explicite, ne pas exécuter de benchmark payant avant.**
**Rollback** : sans objet.
**Estimation** : M.
**Skills recommandés** : `codebase-design`.
**Autorisations manuelles requises** : aucune pour la conception.

### PH0-OCI-08 — Préparer le déploiement de staging

**What to build** : checklist de préparation (secrets, stockage, réseau, Docker Compose local
validé) confirmant que tout est prêt pour un déploiement OCI réel, sans encore le faire.

**Blocked by** : PH0-OCI-02, PH0-OCI-04, PH0-OCI-05, PH0-OCI-06, PH0-OCI-07.

**Contexte** : porte d'entrée vers le track `INFRA` (Phase 1 historique), critères Go/No-Go.

- [ ] Checklist Go/No-Go entièrement cochée.

**Tests attendus** : sans objet (checklist).
**Risques/Rollback** : sans objet.
**Estimation** : S.
**Skills recommandés** : `code-review`.
**Autorisations manuelles requises** : aucune (vérification).

### PH0-OCI-09 — Exécuter le benchmark OCI (ultérieurement)

**What to build** : résultats mesurés (temps, CPU, RAM, E/S) pour la matrice définie dans
`BENCHMARK_PLAN.md` §1, exécutés réellement sur une instance OCI payante.

**Blocked by** : PH0-OCI-03 (protocole reproductible défini), PH0-OCI-07 (protections
budgétaires **impérativement en place avant**).

**Contexte** : reprend et précise l'ancien PH0-02 (remplacement acté avant `AF-RM-01`), ciblé
spécifiquement sur OCI plutôt que sur "au moins un fournisseur" générique.

- [ ] Les 3 tailles de données × 3 volumes de combinaisons × 4 niveaux de workers sont mesurés
      sur au moins une forme OCI (`E5.Flex` recommandé).
- [ ] Les résultats sont consignés (annexe à `BENCHMARK_PLAN.md`, hors périmètre de cette
      mission).
- [ ] L'instance de benchmark est explicitement détruite après usage (pas laissée active).

**Tests attendus** : sans objet (mesure).
**Risques** : facture imprévue si PH0-OCI-07 n'est pas terminé — voir dépendance explicite.
**Rollback** : détruire l'instance si les résultats ne justifient pas la poursuite.
**Estimation** : M.
**Skills recommandés** : aucun skill Claude Code spécifique — exécution manuelle supervisée.
**Autorisations manuelles requises** : dépense financière réelle (instance OCI payante) —
autorisation explicite de l'utilisateur requise avant exécution, conformément aux règles de
sécurité de ce dépôt.

### PH0-OCI-10 — Choisir la forme finale de VM après benchmark

**What to build** : décision finale du profil OCI (forme, OCPU, RAM) pour le staging, avec preuve
issue de PH0-OCI-09.

**Blocked by** : PH0-OCI-09.

**Contexte** : reprend et précise l'ancien PH0-03 (remplacement acté avant `AF-RM-01`). **Note** :
`backtester-ph0-oci-01` (`VM.Standard.E4.Flex`) était une forme **temporaire** dédiée à
`PH0-OCI-01` (clos) — ce ticket reste sur le choix **final** de staging, décision distincte.

- [ ] Profil choisi documenté avec les mesures qui le justifient (référence au benchmark).
- [ ] `requirements-server.txt` installé et validé sur la forme choisie (au-delà de la validation
      minimale de PH0-OCI-01).

**Tests attendus** : `pip install -r requirements-server.txt` réussit sur la forme finale.
**Risques** : voir `RISK_REGISTER.md` — "Coûts serveur imprévus".
**Rollback** : ajuster le profil (formes flexibles OCI, pas de nouvelle commande nécessaire).
**Estimation** : S.
**Skills recommandés** : `WebSearch`/`WebFetch` (revérifier les prix avant tout engagement).
**Autorisations manuelles requises** : engagement de dépense récurrente (staging permanent),
autorisation explicite requise.

### PH1-01 — Prototype file de travaux (RQ vs Celery)

**What to build** : deux prototypes minimaux (un job factice publié/consommé) démontrant le
comportement de reprise après crash, le suivi de progression, et l'annulation, pour RQ et pour
Celery.

**Blocked by** : PH0-OCI-08 (déploiement de staging prêt).

**Contexte** : ADR 0006 (`Decision pending`) — aucune décision technologique prise avant preuve.

- [ ] Les deux prototypes tournent sur le serveur de staging.
- [ ] Le tableau comparatif de `docs/architecture/COMPUTE_AND_JOBS.md` §1 est complété avec des
      mesures réelles (pas seulement des critères qualitatifs).
- [ ] ADR 0006 mise à jour en statut Accepted avec la décision et ses preuves.

**Tests attendus** : test de reprise après `kill -9` d'un worker en cours de traitement.
**Risques** : voir `RISK_REGISTER.md` — "Jobs perdus".
**Rollback** : rester sur le système `subprocess.Popen` actuel si aucune option ne convainc.
**Estimation** : M.
**Skills recommandés** : `tdd`, `implement` (une fois le code de prototype autorisé —
hors périmètre strict de cette mission de planification).
**Autorisations manuelles requises** : autorisation explicite de modifier du code (hors
périmètre de la mission actuelle, purement architecture).
**Décision liée** : `DECISION_BACKLOG.md` — "RQ ou Celery".

### PH1-02 — Squelette Docker Compose (interface + PostgreSQL, sans workers)

**What to build** : un `docker-compose.yml` minimal démarrant l'interface Streamlit actuelle
(`app.py` inchangé) et une instance PostgreSQL vide, accessible en HTTPS sur l'instance OCI de
staging via un reverse proxy — étend le squelette local de PH0-OCI-02 à l'instance OCI réelle.

**Blocked by** : PH0-OCI-08 (déploiement de staging prêt).

**Contexte** : ADR 0009 (Docker Compose staging), ADR 0007 (PostgreSQL métadonnées).

- [ ] `docker-compose up` démarre l'interface, accessible via HTTPS.
- [ ] `.streamlit/config.toml` `headless` passé à `true` pour l'environnement serveur (sans
      casser l'usage local — via variable d'environnement ou fichier de config séparé).
- [ ] Aucun secret dans l'image Docker ni dans le dépôt.

**Tests attendus** : l'interface actuelle (backtest simple) fonctionne à l'identique sur ce
squelette.
**Risques** : voir `RISK_REGISTER.md` — "Complexité prématurée" (mitigé : squelette minimal
d'abord, pas tout le système d'un coup).
**Rollback** : revenir à l'exécution locale, le squelette Docker est additif.
**Estimation** : M.
**Skills recommandés** : `implement`, `code-review`.
**Autorisations manuelles requises** : autorisation explicite de créer les fichiers Docker et de
modifier la configuration Streamlit (hors périmètre de cette mission de planification).

### PH1-03 — Orchestrateur publie sur la file de travaux (remplace `subprocess.Popen` local)

**What to build** : `job_launcher.py` (ou un successeur) publie un travail sur la file choisie
(PH1-01) au lieu de lancer directement un `subprocess.Popen`, tout en préservant le contrat de
job directory à l'identique.

**Blocked by** : PH1-01 (technologie tranchée), PH1-02 (infrastructure de base disponible).

**Contexte** : ADR 0005 (monolithe modulaire + workers).

- [ ] Un job lancé depuis l'UI produit exactement les mêmes fichiers qu'aujourd'hui
      (`progress.json`, `results.csv`, etc.).
- [ ] `assert_no_active_jobs()` est remplacé par une limite de concurrence configurable (pas
      supprimé sans remplacement).
- [ ] Les tests `test_e2e_subprocess.py`/`test_e2e_parallel.py` sont adaptés et passent sur le
      nouveau chemin.

**Tests attendus** : `/tdd` — tests de non-régression sur le contrat de fichiers, test de
publication/consommation via la file.
**Risques** : régression du verrou de concurrence actuel — mitigé par des tests explicites avant
suppression de `assert_no_active_jobs()`.
**Rollback** : garder le chemin `subprocess.Popen` local disponible en repli (flag de
configuration) jusqu'à validation complète du nouveau chemin.
**Estimation** : L.
**Skills recommandés** : `tdd`, `implement`, `code-review`.
**Autorisations manuelles requises** : modification de code d'orchestration — hors périmètre de
cette mission de planification, autorisation explicite requise en son temps.

### PH1-04 — Workers de calcul sur le serveur, backtest + optimisation

**What to build** : au moins un worker backtest et un worker optimisation tournant en conteneur,
consommant la file de travaux, écrivant sur le volume NVMe du serveur.

**Blocked by** : PH1-03.

- [ ] Un job de bout en bout (backtest simple + optimisation réduite) s'exécute entièrement sur
      le serveur, résultat téléchargeable depuis l'UI.

**Tests attendus** : reprise de `test_e2e_parallel.py` adapté au contexte serveur.
**Risques/Rollback** : voir PH1-03.
**Estimation** : M.
**Skills recommandés** : `implement`, `code-review`.
**Autorisations manuelles requises** : idem PH1-03.

### PH1-05 — Secrets serveur (EODHD, IG, PostgreSQL, Redis)

**What to build** : gestion des secrets serveur par variables d'environnement injectées au
démarrage des conteneurs, jamais dans l'image ni dans le dépôt.

**Blocked by** : PH1-02.

**Contexte** : `docs/architecture/SECURITY_AND_OPERATIONS.md` §1-2 — règles déjà respectées côté
EODHD/IG local, à étendre au serveur.

- [ ] Aucun secret visible dans `docker-compose.yml` versionné (fichier `.env` non versionné ou
      coffre de secrets).
- [ ] Statut "configuré/non configuré" affichable sans jamais exposer la valeur.

**Tests attendus** : vérification manuelle qu'aucun secret n'apparaît dans les logs/erreurs.
**Risques** : voir `RISK_REGISTER.md` — "Fuite de secrets".
**Rollback** : sans objet (mesure de sécurité additive).
**Estimation** : S.
**Skills recommandés** : `code-review` (axe sécurité).
**Autorisations manuelles requises** : accès aux vraies clés EODHD/IG pour configurer le serveur
— déjà géré avec prudence par l'utilisateur jusqu'ici, même précaution à conserver.

### PH1-06 — HTTPS via reverse proxy

**What to build** : Caddy ou Nginx (choix en `DECISION_BACKLOG.md`) devant l'interface, HTTPS
actif.

**Blocked by** : PH1-02.

- [ ] L'interface est accessible uniquement en HTTPS, jamais en HTTP non chiffré depuis
      l'extérieur du serveur.

**Tests attendus** : vérification manuelle du certificat.
**Risques/Rollback** : faibles, mesure additive standard.
**Estimation** : S.
**Skills recommandés** : `implement`.
**Autorisations manuelles requises** : nom de domaine/DNS si HTTPS public (à clarifier avec
l'utilisateur le moment venu).

### PH1-07 — Sauvegarde et restauration testées

**What to build** : dump PostgreSQL planifié + sauvegarde sélective de fichiers critiques, avec
une restauration **réellement testée** au moins une fois.

**Blocked by** : PH1-02, PH1-04 (données réelles à sauvegarder).

- [ ] Une restauration complète depuis la sauvegarde reproduit un état fonctionnel.

**Tests attendus** : exercice de restauration en conditions contrôlées (pas en production).
**Risques** : voir `RISK_REGISTER.md` — "Perte de sauvegarde" (le risque que cette tâche mitige).
**Rollback** : sans objet.
**Estimation** : M.
**Skills recommandés** : `implement`.
**Autorisations manuelles requises** : accès au serveur pour l'exercice de restauration.

### PH1-08 — Observabilité minimale

**What to build** : logs structurés par job (déjà partiellement le cas via `logs.txt`), métriques
CPU/RAM/disque du serveur, alerte simple si un job ne progresse plus.

**Blocked by** : PH1-04.

- [ ] Un job bloqué est détectable en moins d'un seuil défini (ex. 10 minutes sans mise à jour de
      `progress.json`).

**Tests attendus** : simuler un job bloqué, vérifier la détection.
**Risques/Rollback** : faibles.
**Estimation** : M.
**Skills recommandés** : `implement`.
**Autorisations manuelles requises** : aucune particulière.

---

## Principe de non-précision

Aucun ticket macro des sections 6-7 ci-dessus n'est estimé en jours/points précis — leur ordre de
grandeur (S/M/L/XL) reste indicatif tant qu'ils n'ont pas été affinés au moment de leur prise en
charge réelle, exactement comme dans l'ancienne organisation par Phases.
