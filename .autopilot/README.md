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
  entre chaque étape, jamais en plein milieu d'une opération) en plus de la libération
  inconditionnelle du verrou.
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

180 tests Autopilot dédiés, tous verts. Suite complète du projet également verte (1190/1190).

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

Tâche planifiée Windows (déclenchement à la connexion, jamais SYSTEM, jamais un autre compte) :

```powershell
.\scripts\autopilot\install_task.ps1
.\scripts\autopilot\uninstall_task.ps1
```

## Fichiers de ce dossier

- `policy.json` — résumé lisible de la politique de sécurité (l'application réelle testée vit
  dans `scripts/autopilot/git_safety.py`, jamais dérivée automatiquement de ce JSON).
- `missions.json` — file de missions (versionné, source de vérité partagée), schéma V1.1 enrichi.
- `prompts/` — un prompt par mission référencée dans `missions.json` (versionné), y compris
  `canary-v1-1.md` (fixture de smoke-test réutilisable pour valider une future modification de la
  boucle) et `af-v02-slice-2.md` (mission scientifique réelle, scope détail dans `AI_HANDOFF.md`).
- `state/` — état runtime (verrou, signal d'arrêt, état courant, historique, logs) — **jamais
  versionné** (`.gitignore`), local à chaque machine.

## Sécurité — rappel des interdictions absolues (mission §9, testées)

Jamais : force push, réécriture d'historique publié, `--no-verify`, `reset --hard` destructeur,
`clean` destructeur, suppression de branche distante, écrasement de modifications non comprises,
modification de `app_corrupted_backup.py`, versionnement de secrets/`nasdaq_3m.csv`/gros
artefacts, accès `FINAL_HOLDOUT` automatique, ordre IG live, `--dangerously-skip-permissions`
comme solution générale, push sur divergence distante non comprise.
