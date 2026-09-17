# Archive — BLOCKED_SAFETY rencontré dans le dossier principal (2026-09-17)

Trace de l'unique tentative d'ignition réelle d'`AF-V-02-SLICE-2` lancée depuis le dossier
principal (`C:\Users\Mira Alexandre\Desktop\Backtest Nasdaq revolution 3Mn`), AVANT la création du
worktree permanent dédié documentée par la mission de finalisation. Conservée telle quelle, sans
réécriture — ce blocage était un vrai garde-fou de sécurité qui a fonctionné correctement, jamais
une anomalie à corriger.

## Cause

`requires_clean_worktree=True` (déclaré par la mission `AF-V-02-SLICE-2`) a détecté des
modifications non liées déjà présentes dans l'index/l'arbre de travail du dossier principal au
moment de `cmd_start` :

- `AGENTS.md` (modifié, staged)
- `docs/adr/0016-spec-kit-and-skill-orchestration-policy.md` (ajouté, staged)
- `docs/agents/skills-usage.md` (modifié, staged)
- `=1.12.0` (non suivi)

Ces fichiers sont un travail préexistant de l'utilisateur, explicitement protégé — instruction
permanente de ne jamais les committer/stasher/modifier depuis la mission de finalisation. Le
superviseur a correctement refusé de démarrer sur un état ambigu plutôt que de risquer de les
inclure dans un commit Autopilot.

## Décision

L'utilisateur a tranché explicitement : conserver intégralement ces fichiers dans le dossier
principal et utiliser un worktree Git permanent DÉDIÉ à l'Autopilot
(`C:\Users\Mira Alexandre\Desktop\backtest-nasdaq-revolution-autopilot-permanent`, branche
`autopilot/permanent`) plutôt que d'exiger une décision humaine sur le sort de ces fichiers. Le
verrou/signal d'arrêt de l'Autopilot ont depuis été rendus globaux au dépôt (`git
rev-parse --git-common-dir`) pour qu'un superviseur démarré depuis N'IMPORTE QUEL worktree —
dossier principal ou worktree permanent — ne puisse jamais tourner en concurrence avec un autre.

## État exact archivé (copie intégrale, jamais modifiée)

L'état ci-dessous est une copie EXACTE de
`C:\Users\Mira Alexandre\Desktop\Backtest Nasdaq revolution 3Mn\.autopilot\state\current_state.json`
tel qu'observé le 2026-09-17T19:xx UTC — ce fichier reste `.gitignore`d et propre à ce worktree, il
n'a jamais été committé ni modifié par cette archive :

```json
{
  "phase": "BLOCKED_SAFETY",
  "mission_id": null,
  "timestamp_utc": "2026-09-17T15:47:27.142438+00:00",
  "branch": "master",
  "head": "8d40badb1a084a0fddeaa0b34bc06e2070be9051",
  "origin_master": "8d40badb1a084a0fddeaa0b34bc06e2070be9051",
  "scope_files": [],
  "next_action": null,
  "attempt_count": 0,
  "tests_status": null,
  "review_status": null,
  "stop_reason": "mission AF-V-02-SLICE-2 exige un worktree propre (requires_clean_worktree=True) mais des modifications non liées sont présentes — jamais démarrée sur un état ambigu (mission Autopilot V1.1 §4/§13).",
  "claude_session_id": null,
  "artifacts": [],
  "developer_session_id": null,
  "reviewer_session_id": null,
  "resume_to_phase": null,
  "pending_findings": [],
  "last_commit_sha": null,
  "last_push_sha": null,
  "diagnostic_attempted": false
}
```

## Reprise

Ce blocage n'a PAS été résolu automatiquement (catégorie `dirty_worktree` non taguée sur cet état
pré-finalisation, `blocked_reason_category` n'existait pas encore à ce moment). Il reste
volontairement figé dans le dossier principal comme trace historique — la mission
`AF-V-02-SLICE-2` a été réellement reprise et exécutée depuis le worktree permanent (état séparé,
propre à cette branche), jamais en effaçant ni en désactivant `requires_clean_worktree` pour
contourner ce blocage initial.
