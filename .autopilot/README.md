# AlphaForge Autopilot — Bootstrap V1 (2026-09-17)

Superviseur autonome auditable pour enchaîner les missions AlphaForge V2 (code → tests → review →
corrections → commit → push → mission suivante) sans confirmation humaine à chaque étape, dans les
limites strictes définies ci-dessous. Construit lors de la mission « Bootstrap AlphaForge
Autopilot V1 en cours d'AF-V-02 » (2026-09-17) — voir `AI_HANDOFF.md` pour le rapport complet de
cette mission (fichiers créés/modifiés, tests, review, décisions).

## Ce que fait réellement ce Bootstrap V1

- Une **machine à états explicite** (18 états, `scripts/autopilot/state_machine.py`) pilotant la
  boucle : `PLANNING → DEVELOPING → TESTING → REVIEWING → (CORRECTING) → PRE_COMMIT_CHECK →
  COMMITTING → PUSHING → CHECKPOINTED → NEXT_MISSION`.
- Un **état persisté atomiquement** (`.autopilot/state/current_state.json`, réécrit à chaque
  transition) + un **historique borné** (`current_state.json.history.json`) pour l'audit.
- Une **politique de sécurité Git** (`scripts/autopilot/git_safety.py`) appliquée AVANT toute
  commande réelle : force push, `reset --hard`, `clean` destructeur, `--no-verify`, suppression de
  branche distante, ajout global aveugle (`add -A`/`.`) sont structurellement refusés — jamais une
  question de discipline humaine seule.
- Des **fichiers protégés** (`app_corrupted_backup.py`, `nasdaq_3m.csv`) qui ne peuvent jamais
  entrer dans le scope d'un commit Autopilot.
- Une **détection prudente de dépassement de quota/erreur réseau/authentification/crash**
  (`scripts/autopilot/quota_detector.py`) — heuristique par mots-clés, documentée comme
  imparfaite, jamais un détecteur infaillible.
- Une **politique d'escalade anti-boucle** : un même échec répété (`should_escalate()`) déclenche
  un `HUMAN_GATE_REQUIRED` plutôt qu'une tentative infinie.
- Un **format de rapport Human Gate** structuré (`scripts/autopilot/human_gate.py`) — français
  simple, décision/raison/recommandation/options (1 à 3, une seule recommandée)/risques/
  conséquences.
- Un **verrou mono-instance** (`SingleInstanceLock`) empêchant deux superviseurs de tourner en
  même temps sur la même machine.
- Une **file de missions** persistée (`.autopilot/missions.json`) avec dépendances explicites —
  jamais une mission sélectionnée avant que ses prérequis soient `DONE`.
- Des **commandes CLI** (`scripts/autopilot/cli.py`, appelées par les scripts PowerShell) :
  `status` (résumé lisible), `stop` (libère le verrou proprement), `start`/`resume` (construisent
  le superviseur réel — voir limites ci-dessous).

121 tests dédiés (`tests/test_autopilot_*.py`, `tests/test_atomic_json_store.py`), tous verts,
aucun sous-processus Claude/Git réel exécuté par la suite de tests — uniquement des doublures
injectées (mission Phase D : « dry-run sûr »). Revu par 2 sous-agents indépendants
(sécurité/architecture, reproductibilité/scope) : 3 BLOCKER et 4 IMPORTANT trouvés (transitions
d'état manquantes pour des échecs pourtant ordinaires, échecs Git réels non rattrapés, validation
de scope incomplète au commit) — tous corrigés avant ce commit, détail dans `AI_HANDOFF.md` §24.

## Limites connues de ce V1 (documentées, pas cachées)

- **`start`/`resume` construisent un superviseur réel mais n'ont jamais été exécutés en
  conditions réelles par cette mission** — aucune boucle autonome n'a réellement tourné, aucun
  `claude -p` récursif n'a réellement été invoqué. La logique est prouvée par tests avec des
  doublures ; l'exécution réelle reste un choix explicite de l'utilisateur (voir « Démarrer pour
  de vrai » ci-dessous).
- **La review indépendante n'est pas encore réellement câblée** dans `real_reviewer_fn`
  (`cli.py`) — retourne toujours « propre » pour l'instant. Mission §11 exige un contexte
  vraiment séparé du développeur (ex. un second appel `claude -p` sans l'historique de
  justification) : à implémenter avant tout usage réel en production.
- **Le verrou mono-instance n'est pas robuste multi-OS/production** (pas de détection de PID
  mort) — suffisant pour éviter un double-lancement accidentel sur cette machine, pas pour un
  environnement multi-machine.
- **L'historique des signatures d'échec anti-boucle n'est PAS persisté à travers un crash** — il
  vit en mémoire du process superviseur. Après un vrai crash/redémarrage, l'escalade anti-boucle
  repart de zéro pour la mission en cours (limitation documentée, pas un oubli).
- **La tâche planifiée Windows n'a pas été enregistrée par cette mission** — les scripts
  d'installation/désinstallation existent (`scripts/autopilot/install_task.ps1`/
  `uninstall_task.ps1`) mais n'ont pas été exécutés. Décision volontaire : ne pas activer un
  déclenchement automatique et non supervisé avant que l'utilisateur ait vu et approuvé le
  système une première fois.
- **La file de missions est intentionnellement vide de tout vrai travail** (`EXAMPLE-001` est un
  gabarit `BLOCKED`) — voir `prompts/example.md` pour pourquoi AF-V-02 Slice 2 n'y a pas été
  placée automatiquement.

## Démarrer pour de vrai (quand vous êtes prêt·e)

```powershell
# 1. Remplacer le gabarit de mission par une vraie mission (voir .autopilot/prompts/example.md)
# 2. Démarrer
.\scripts\autopilot\start.ps1

# Consulter l'état
.\scripts\autopilot\status.ps1

# Arrêter proprement
.\scripts\autopilot\stop.ps1

# Reprendre après arrêt/crash/redémarrage
.\scripts\autopilot\resume.ps1
```

Pour un déclenchement automatique au démarrage de Windows (nécessite des droits administrateur
pour l'enregistrement — jamais contourné) :

```powershell
.\scripts\autopilot\install_task.ps1     # installe la tâche planifiée AlphaForgeAutopilot
.\scripts\autopilot\uninstall_task.ps1   # la retire
```

## Fichiers de ce dossier

- `policy.json` — résumé lisible de la politique de sécurité (l'application réelle testée vit
  dans `scripts/autopilot/git_safety.py`, jamais dérivée automatiquement de ce JSON).
- `missions.json` — file de missions (versionné, source de vérité partagée).
- `prompts/` — un prompt par mission référencée dans `missions.json` (versionné).
- `state/` — état runtime (verrou, état courant, historique, logs) — **jamais versionné**
  (`.gitignore`), local à chaque machine.

## Sécurité — rappel des interdictions absolues (mission §9, testées)

Jamais : force push, réécriture d'historique publié, `--no-verify`, `reset --hard` destructeur,
`clean` destructeur, suppression de branche distante, écrasement de modifications non comprises,
modification de `app_corrupted_backup.py`, versionnement de secrets/`nasdaq_3m.csv`/gros
artefacts, accès `FINAL_HOLDOUT` automatique, ordre IG live, `--dangerously-skip-permissions`
comme solution générale.
