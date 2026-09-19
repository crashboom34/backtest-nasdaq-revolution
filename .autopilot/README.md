# AlphaForge Autopilot — V1.1, opérationnel (2026-09-17)

Superviseur autonome auditable pour enchaîner les missions AlphaForge V2 (code → tests → review →
corrections → commit → push → mission suivante) sans confirmation humaine à chaque étape, dans les
limites strictes définies ci-dessous. Bootstrap V1 construit lors de la mission « Bootstrap
AlphaForge Autopilot V1 en cours d'AF-V-02 » (2026-09-17, commit `39e002a`) ; rendu réellement
opérationnel et validé en conditions réelles lors de la mission « Autopilot V1.1 opérationnel »
(2026-09-17) — voir `AI_HANDOFF.md` pour le rapport complet de chaque mission.

## Ce que fait réellement ce V1.1 (vérifié en conditions réelles, pas seulement testé avec des doublures)

- Une **machine à états explicite** (18 états, `scripts/autopilot/state_machine.py`) pilotant la
  boucle : `PLANNING → DEVELOPING → TESTING → REVIEWING → (CORRECTING) → PRE_COMMIT_CHECK →
  COMMITTING → PUSHING → CHECKPOINTED → NEXT_MISSION`, avec reprise réelle depuis
  `WAITING_FOR_CLAUDE`/`WAITING_FOR_EXTERNAL_RESOURCE` vers la phase interrompue.
- **`start`/`resume` exécutent RÉELLEMENT la boucle** (`run_until()`) — plus un simple message de
  statut. Prouvé par un canary réel de bout en bout (voir ci-dessous).
- Un **Developer réel** : lit le vrai `prompt_file` de la mission, son scope
  (`allowed_paths`/`forbidden_paths`), les contrats scientifiques concernés, les findings de
  review à corriger ; invoque `claude -p` réellement ; les fichiers modifiés viennent de l'état
  Git réel (`git status --porcelain`), jamais inventés.
- Un **Reviewer réellement indépendant** : nouvelle session `claude -p` à chaque appel (jamais
  `--resume` la session du développeur), `permission_mode="plan"` (ne peut jamais éditer de
  fichier lui-même), sortie structurée validée par schéma JSON (`--json-schema`). Un échec de
  parsing de la sortie structurée est traité comme un échec TECHNIQUE de la review, jamais
  silencieusement interprété comme "propre" (voir bug réel trouvé/corrigé ci-dessous).
- Un **Tester réel** : exécute les `targeted_tests` de la mission d'abord (échec rapide), impose
  la suite complète pour une mission à risque élevé ou touchant des contrats scientifiques
  déclarés.
- Un **état persisté atomiquement** (`.autopilot/state/current_state.json`, réécrit à chaque
  transition) + un **historique borné** pour l'audit — porte désormais aussi `head`/
  `origin_master` réels, `last_commit_sha`/`last_push_sha` (idempotence), `developer_session_id`/
  `reviewer_session_id`, `resume_to_phase`, `pending_findings`, `diagnostic_attempted`.
- Un **verrou mono-instance ATOMIQUE et conscient du PID** (`os.O_CREAT|O_EXCL`, détection d'un
  PID mort sous Windows via `ctypes`/`OpenProcess` — un verrou orphelin est récupéré, jamais un
  verrou tenu par un process vivant).
- Un **signal d'arrêt coopératif** (`autopilot stop` dépose un signal, `run_until()` le vérifie
  entre chaque étape, jamais en plein milieu d'une opération). Le verrou n'est PLUS jamais libéré
  de force par `stop` tant qu'il est détenu par un process réellement vivant (finalisation
  sécurité, 2026-09-17) — seul le PROPRIÉTAIRE libère son propre verrou une fois l'arrêt
  effectif ; `force_release()` reste réservé au nettoyage d'un verrou authentiquement orphelin.
- Un **schéma de mission enrichi et validé strictement** (`allowed_paths`/`forbidden_paths`/
  `targeted_tests`/`regression_tests`/`risk_level`/`max_attempts`/`max_budget_usd`/
  `requires_clean_worktree`/`scientific_contracts`/`human_gate_conditions`/`completion_evidence`)
  — un fichier de missions absent/mal formé/invalide route vers `BLOCKED_SAFETY`, jamais une file
  vide silencieuse ni un faux `COMPLETED`. `requires_clean_worktree` (`True` par défaut) est
  RÉELLEMENT vérifié avant de démarrer une mission.
- **Le commit/push sont idempotents** à travers un crash simulé (`last_commit_sha`/
  `last_push_sha`) — jamais un double commit ni un double push. Le flip `DONE` d'une mission fait
  désormais partie du MÊME commit que son propre travail (bug réel trouvé et corrigé : avant ce
  correctif, ce flip avait lieu après le push et n'était donc jamais poussé).
- **Un diagnostic indépendant est tenté une fois avant d'escalader** vers un Human Gate sur un
  échec répété identique (mission §8) — jamais une boucle non bornée.
- Une **politique de sécurité Git** (`scripts/autopilot/git_safety.py`) appliquée AVANT toute
  commande réelle : force push, `reset --hard`, `clean` destructeur, `--no-verify`, suppression de
  branche distante, ajout global aveugle sont structurellement refusés. `RealGitOps.commit()`
  revalide secrets/gros fichiers/scope sur l'INDEX RÉEL juste avant de committer ;
  `RealGitOps.push()` exécute `git fetch origin` et vérifie la divergence réelle (jamais un push
  aveugle, jamais forcé).
- Des **fichiers protégés** (`app_corrupted_backup.py`, `nasdaq_3m.csv`) qui ne peuvent jamais
  entrer dans le scope d'un commit Autopilot.
- Des **commandes CLI** (`scripts/autopilot/cli.py`) : `status`, `stop` (signal + verrou),
  `start`/`resume` (boucle réelle).

206 tests Autopilot dédiés, tous verts. Suite complète du projet également verte (1261/1261).

## Preuve réelle — canary V1.1 (2026-09-17)

Un canary end-to-end RÉEL (aucune doublure) a été exécuté sur la branche isolée
`autopilot/v1-1-operational` : vraie sélection de mission, vrai appel `claude -p` Developer
(a écrit `.autopilot/canary/CANARY_MARKER.md` avec l'horodatage réel demandé, en restant
strictement dans le scope autorisé), vrais tests ciblés (6 passed), vrai appel `claude -p`
Reviewer indépendant (schéma JSON), vrai commit Git (`f2e2611`), vrai push. Trois bugs réels ont
été trouvés et corrigés PENDANT ce canary (pas seulement en revue statique) :

1. **`sys.executable` vs chemin `.venv` codé en dur** — le Tester réel utilisait un chemin relatif
   supposant un `.venv/` local sous `REPO_ROOT` ; cassait dans un déploiement qui n'a pas son
   propre venv (le worktree isolé de cette mission). Corrigé : `sys.executable`.
2. **Décodage Windows non explicite** — `subprocess.run(text=True)` utilisait la locale Windows
   (cp1252) par défaut, a fait planter un thread lecteur sur le premier caractère accentué (dépôt
   en français). Corrigé : `encoding="utf-8", errors="replace"` explicite partout.
3. **Sortie structurée du Reviewer silencieusement mal interprétée** — la review indépendante
   réelle a retourné `"0 finding(s) — verdict=?"` : le parsing de `result` (une chaîne JSON
   re-encodée, potentiellement entourée de texte) avait échoué, retombant sur `body={}`, ce qui
   ressemblait exactement à une review propre. Un second sondage réel a révélé un champ
   `structured_output` natif, fiable, jusque-là ignoré. Corrigé : `structured_output` devient la
   source prioritaire, et l'absence de `verdict`/`findings` est désormais traitée comme un échec
   TECHNIQUE de la review, jamais comme "propre".

Deux autres bugs réels ont été trouvés en retraçant précisément ce scénario (pas empiriquement
via le canary lui-même, mais en creusant sa cause) :

4. **Le flip `DONE` d'une mission n'était jamais committé** — avait lieu après le push, dans
   `_handle_next_mission()`. Corrigé : déplacé dans `_handle_committing()`, même commit que le
   travail de la mission, idempotent.
5. **`mission.requires_clean_worktree` déclaré mais jamais vérifié** — exactement le scénario qui
   avait pollué le scope du canary (des édits d'ingénierie non committés mélangés au travail du
   canary). Corrigé : vérifié réellement dans `_handle_planning()`.
6. **Une mission disparaissant en cours de route** (`missions.json` corrompu/modifié pendant
   DEVELOPING/TESTING/REVIEWING/CORRECTING) laissait invoquer — donc facturer — un appel Claude
   réel sur un contexte quasi vide avant que la corruption ne soit détectée à `COMMITTING`. Bloque
   désormais immédiatement.

Une revue indépendante à 2 axes (sécurité/architecture, reproductibilité/scope) sur le diff
complet a ensuite trouvé **3 BLOCKER supplémentaires, tous empiriquement reproduits**, tous
corrigés : `REVIEWING` ne pouvait pas légalement escalader vers `HUMAN_GATE_REQUIRED` (crash sur
tout échec de review répété, pourtant ordinaire) ; le repli de reprise depuis
`WAITING_FOR_CLAUDE` (`PLANNING`) n'était pas légal (crash sur tout état antérieur à
`resume_to_phase`) ; sous Windows, un `OpenProcess` refusé (process vivant mais protégé/EDR) était
confondu avec un process mort, permettant de voler un verrou actif. Plus 2 IMPORTANT : des
commandes Git en lecture seule contournaient encore `git_safety.check_git_command()` ; aucun
sous-processus n'avait de `timeout=`, rendant l'arrêt coopératif sans effet pendant un appel
bloqué — les deux corrigés.

## Finalisation opérationnelle — worktree permanent (2026-09-17, suite)

Une seconde mission de finalisation a rendu ce V1.1 sûr pour une exécution enchaînée réelle
(AF-V-02 Slice 2), après qu'une tentative d'ignition depuis le dossier principal a été refusée par
`requires_clean_worktree` sur des modifications préexistantes de l'utilisateur (voir
`.autopilot/archive/2026-09-17-blocked-safety-main-repo-dirty-worktree.md`). Décision retenue :
conserver ces fichiers intégralement dans le dossier principal et exécuter l'Autopilot depuis un
**worktree Git permanent dédié** :

- Chemin : `C:\Users\Mira Alexandre\Desktop\backtest-nasdaq-revolution-autopilot-permanent`
- Branche : `autopilot/permanent`
- `.venv/` : JONCTION NTFS vers le `.venv/` du dossier principal (aucun téléchargement dupliqué).
- `nasdaq_3m.csv` : copié depuis le dossier principal (gitignoré, nécessaire à la régression).
- Jamais supprimé après usage — worktree durable, pas jetable comme les précédents.

Cette mission a corrigé, avec un test de régression dédié pour chacun (TDD, écrit rouge avant
correction) :

- **Arrêt et verrou** : `cmd_stop()` ne vole plus jamais le verrou d'un process réellement vivant.
- **Review complète** : couverture de TOUS les changements (suivis, nouveaux, suppressions,
  renommages), plus de troncature silencieuse à 20000 caractères, découpage en lots vérifié
  explicitement contre la liste attendue. La couverture (`reviewed_files`) est désormais
  OBLIGATOIRE avant tout commit, jamais un contrôle opt-in.
- **Diffing sans toucher l'index réel** : un index Git TEMPORAIRE (`GIT_INDEX_FILE`), jamais
  `.git/index`, rend les nouveaux fichiers visibles au diff sans jamais polluer durablement l'état
  du worktree — l'ancienne version laissait des entrées `intent-to-add` définitivement en place si
  une mission n'atteignait jamais `COMMITTING`.
- **Tests rouges → correction réelle** : un échec de test route désormais TOUJOURS vers
  `CORRECTING` (un vrai rappel du Developer avec le retour exploitable), y compris après le cycle
  de diagnostic pré-Human-Gate — jamais une simple retentative de `tester_fn()` sans rien changer.
- **Findings préservés** : une retentative de CORRECTING qui échoue pour une raison technique sans
  rapport ne perd plus les findings ORIGINAUX qu'elle doit encore corriger.
- **Callbacks protégés** : une exception non gérée de `developer_fn`/`tester_fn`/`reviewer_fn` ne
  crashe plus jamais le superviseur — convertie en échec ordinaire, classifiée normalement.
- **Reprise contrôlée après `BLOCKED_SAFETY`** : catégories causales explicites
  (`blocked_reason_category`), seules `dirty_worktree`/`disk_space` ont une résolution
  automatique connue (revérifiée à chaque fois) ; tout le reste reste bloqué indéfiniment sans
  intervention externe réelle — jamais un effacement d'état.
- **Preuves liées à la bonne mission** : une nouvelle mission ne peut plus afficher les preuves de
  tests/review de la mission précédente avant d'avoir réellement exécuté les siennes.
- **Branche/push explicites** : `RealGitOps` vérifie que HEAD correspond à la branche déclarée,
  pousse un refspec explicite (`branche:référence-distante`, jamais `master` supposé), et confirme
  le SHA distant après coup.

Deux revues indépendantes (sécurité/architecture, reproductibilité/scope) sur ce diff ont ensuite
trouvé 2 IMPORTANT supplémentaires, tous deux corrigés : le code de retour de `git read-tree HEAD`
n'était pas vérifié (un index temporaire sous-seedé aurait montré un fichier modifié comme
entièrement supprimé au Reviewer) ; le nettoyage du répertoire temporaire de review ne couvrait pas
un échec survenant PENDANT sa propre initialisation. Une note MINOR reste documentée sans être
jugée bloquante : le marqueur textuel distinguant un finding original d'une note de constat
d'échec (`"Échec précédent à corriger : "`) pourrait théoriquement entrer en collision avec un
finding réel qui commencerait par cette même phrase exacte — probabilité jugée négligeable en
pratique (nécessiterait que le Reviewer/Tester reproduise cette phrase française mot pour mot).

## Autorisation permanente — slices AF-V-02 déjà cadrées par la spécification validée (2026-09-18)

Décision explicite de l'utilisateur : les tranches (« slices ») d'implémentation d'`AF-V-02`
(Walk-Forward), dès lors qu'elles dérivent STRICTEMENT du périmètre déjà décidé par
`docs/adr/0021-walk-forward-rolling-calendar-v1.md` et de la section « Ce qui N'EST PAS dans cette
tranche » de la tranche précédente, sont **pré-autorisées à s'enchaîner sans demande de
confirmation individuelle** pour chacune — l'utilisateur n'a plus besoin de valider explicitement
chaque nouvelle tranche avant sa mise en file/son exécution.

**Cette autorisation reste strictement bornée** — elle ne supprime AUCUNE protection scientifique
ni opérationnelle existante, ne s'étend à AUCUN autre epic/mission que les tranches AF-V-02 déjà
couvertes par l'ADR 0021, et ne dispense JAMAIS :
- du TDD strict (RED confirmé avant implémentation) ;
- de la review indépendante avant tout commit/push ;
- des `human_gate_conditions` propres à chaque mission (`FINAL_HOLDOUT`, stratégie étalon Perfect
  Revolution V1, tout conflit scientifique réellement indéterminé par l'ADR) ;
- des budgets déjà établis (`max_budget_usd`/`max_attempts` par mission — jamais relevés
  unilatéralement pour « faire passer » une tranche) ;
- de `requires_clean_worktree` (jamais désactivé globalement) ;
- de la distinction stricte entre une limite de quota/dépenses Claude (jamais un Human Gate
  scientifique — route vers `WAITING_FOR_CLAUDE`, voir `classify_failure()`) et un authentique
  conflit scientifique (seul cas légitime de `HUMAN_GATE_REQUIRED`).

Chaque nouvelle tranche doit néanmoins être préparée avec la même rigueur qu'une mission mise en
file manuellement : un prompt dédié (`prompts/af-v02-slice-N.md`) citant précisément les décisions
ADR concernées et la section « hors scope » de la tranche précédente (jamais un contenu supposé à
partir du seul numéro de tranche), une entrée `missions.json` avec scope/tests/`human_gate_conditions`/
`completion_evidence` explicites, avant toute mise en file.

## Coût réel observé (à budgéter, jamais négligeable)

Deux sondages réels indépendants (`claude -p --output-format json`) ont mesuré ~0,32-0,41 $ pour
UN SEUL tour, même trivial — dominé par la création de cache du contexte projet
(CLAUDE.md/mémoire/skills, ~53-57k tokens), pas par le travail réel demandé. `DEFAULT_MAX_BUDGET_USD
= 3.0` (Developer/Reviewer), plafond réduit pour le diagnostic (`min(1.0, budget mission)`,
modèle `claude-haiku-4-5`). Une mission peut définir `max_budget_usd` pour ajuster.

## Limites connues (documentées, pas cachées)

- **Le verrou mono-instance détecte un PID mort mais reste single-machine** — pas un verrou
  distribué multi-machine de niveau production.
- **L'historique des signatures d'échec anti-boucle n'est PAS persisté à travers un crash réel**
  — repart à zéro en mémoire pour la mission en cours après un vrai redémarrage.
- **`changed_files` reflète tout le working tree dirty** (`git status --porcelain`), pas un diff
  avant/après strict de ce qu'UNE invocation Developer a touché — `requires_clean_worktree=True`
  (défaut) protège contre la contamination de scope en refusant de démarrer sur un worktree déjà
  sale, mais ne distingue pas "le Developer a touché ce fichier" de "il était déjà sale et le
  Developer ne l'a pas retouché".
- **La tâche planifiée Windows** — voir état exact dans `AI_HANDOFF.md` (installée ou non selon le
  résultat de cette mission).

## Démarrer / suivre / arrêter / reprendre

```powershell
.\scripts\autopilot\start.ps1      # démarre RÉELLEMENT la boucle
.\scripts\autopilot\status.ps1     # état courant (mission, phase, HEAD, origin/master, tests, review)
.\scripts\autopilot\stop.ps1       # signal d'arrêt coopératif + libération du verrou
.\scripts\autopilot\resume.ps1     # reprise réelle (reconcilie l'état avec le dépôt avant de reprendre)
```

Tâche planifiée Windows (déclenchement à la connexion **et** répété toutes les 30 minutes,
indéfiniment — voir « Reprise automatique » ci-dessous ; jamais SYSTEM, jamais un autre compte) :

```powershell
.\scripts\autopilot\install_task.ps1
.\scripts\autopilot\uninstall_task.ps1
```

### Reprise automatique après une pause d'attente externe (2026-09-19)

Bug réel confirmé : `WAITING_FOR_CLAUDE`/`WAITING_FOR_EXTERNAL_RESOURCE` sont des états d'ATTENTE
passifs — rien ne les revérifie de lui-même. Avant ce correctif, la tâche planifiée ne se
déclenchait qu'à la connexion : une fois une limite de dépenses Claude réinitialisée (ou une
panne réseau résolue), rien ne relançait l'Autopilot sans une invocation manuelle de
`autopilot resume`. La tâche porte désormais un SECOND déclencheur, répétant `resume.ps1` toutes
les 30 minutes indéfiniment, en plus du déclenchement à la connexion — sûr par construction,
jamais une nouvelle protection contournée :

- Une instance déjà active fait simplement échouer l'acquisition du verrou fichier et sort
  aussitôt (`MultipleInstances=IgnoreNew` de Task Scheduler ajoute une seconde couche).
- Un `HUMAN_GATE_REQUIRED` n'a aucun handler dans `run_one_step()` — une tentative périodique le
  laisse strictement inchangé, jamais résolu automatiquement (seule
  `autopilot resolve-human-gate` explicite le peut).
- Aucun plafond n'est jamais relevé ni réinitialisé par cette tentative périodique — si la cause
  externe persiste, elle échoue et re-parque exactement comme avant, sans effet de bord.
- Un `BLOCKED_SAFETY` (`dirty_worktree`/`disk_space`) est également revérifié à chaque tentative
  (`_handle_blocked_safety()`, déjà existant) — profite de la même cadence.

## Fichiers de ce dossier

- `policy.json` — résumé lisible de la politique de sécurité (l'application réelle testée vit
  dans `scripts/autopilot/git_safety.py`, jamais dérivée automatiquement de ce JSON).
- `missions.json` — file de missions (versionné, source de vérité partagée), schéma V1.1 enrichi.
- `prompts/` — un prompt par mission référencée dans `missions.json` (versionné), y compris
  `canary-v1-1.md` (fixture de smoke-test réutilisable pour valider une future modification de la
  boucle) et `af-v02-slice-2.md` (mission scientifique réelle, scope détail dans `AI_HANDOFF.md`).
- `state/` — état courant/historique/logs (`current_state.json`, `.history.json`) — **jamais
  versionné** (`.gitignore`), propre à CHAQUE worktree/branche (chacun poursuit son propre travail).
  Le **verrou mono-instance et le signal d'arrêt**, en revanche, vivent désormais sous le
  répertoire `.git` RÉELLEMENT commun à tous les worktrees du dépôt (`git rev-parse
  --git-common-dir`, finalisation sécurité 2026-09-17) — jamais sous `state/`, précisément pour
  qu'un superviseur démarré depuis N'IMPORTE QUEL worktree ne puisse jamais tourner en concurrence
  avec un autre sur la même file de missions.
- `archive/` — traces figées d'événements passés (ex. un `BLOCKED_SAFETY` rencontré avant la
  création d'un nouveau worktree) — **versionné**, jamais réécrit après coup.

## Sécurité — rappel des interdictions absolues (mission §9, testées)

Jamais : force push, réécriture d'historique publié, `--no-verify`, `reset --hard` destructeur,
`clean` destructeur, suppression de branche distante, écrasement de modifications non comprises,
modification de `app_corrupted_backup.py`, versionnement de secrets/`nasdaq_3m.csv`/gros
artefacts, accès `FINAL_HOLDOUT` automatique, ordre IG live, `--dangerously-skip-permissions`
comme solution générale, push sur divergence distante non comprise.
