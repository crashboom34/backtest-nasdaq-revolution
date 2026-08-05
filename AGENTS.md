# AGENTS.md

Instructions pour **Codex** dans ce dépôt (`crashboom34/backtest-nasdaq-revolution`). Ce fichier
est le pendant Codex de `CLAUDE.md` (lu par Claude Code) — les sections communes aux deux agents
sont maintenues identiques entre les deux fichiers ; voir `docs/agents/` pour la documentation
partagée détaillée.

## À propos du projet

Application de backtest de stratégies de trading algorithmique (Streamlit), aujourd'hui centrée
sur l'indice US100 (NASDAQ) en timeframe M3, données MetaTrader 5. Voir `README.md` et
`AI_HANDOFF.md` pour le contexte fonctionnel détaillé, et `CONTEXT.md` pour le glossaire métier.

## Agent skills

Les [skills d'ingénierie de Matt Pocock](https://github.com/mattpocock/skills) sont installés
dans ce dépôt, en fichiers complets (pas seulement `SKILL.md`) :

- **Emplacement pour Codex** : `.agents/skills/<skill-name>/` — Codex découvre ces skills depuis
  ce dossier projet ; comme il n'y a pas de commandes slash, **mentionner le nom du skill
  explicitement** dans l'instruction (ex. "utilise le skill `to-tickets` pour découper cette
  spec").
- **Emplacement pour Claude Code** : `.claude/skills/<skill-name>/` — Claude Code utilise les
  commandes slash quand elles sont disponibles (ex. `/grill-with-docs`).
- Les deux dossiers contiennent un contenu identique. Voir `docs/adr/0001-shared-skills-for-claude-code-and-codex.md`
  pour le choix de les dupliquer plutôt que de partager un seul emplacement.

Dix skills installés : `setup-matt-pocock-skills`, `grill-with-docs`, `domain-modeling`,
`codebase-design`, `improve-codebase-architecture`, `to-spec`, `to-tickets`, `implement`,
`tdd`, `code-review`.

- **Tickets** : gérés dans les **GitHub Issues** du dépôt `crashboom34/backtest-nasdaq-revolution`.
  Détails et conventions : `docs/agents/issue-tracker.md`.
- **Modèle de domaine** : mono-contexte. `CONTEXT.md` (racine du dépôt) est la source principale
  de terminologie métier. ADR dans `docs/adr/`. Voir `docs/agents/domain.md` pour comment lire et
  mettre à jour ces documents.
- **Documentation agents** : `docs/agents/` (ce dossier), y compris les workflows détaillés dans
  `docs/agents/skills-usage.md`.
- Codex (et Claude Code) doivent utiliser les skills disponibles lorsqu'ils correspondent à la
  tâche en cours — voir `docs/agents/skills-usage.md` pour les enchaînements recommandés
  (nouvelle fonctionnalité, amélioration d'architecture, correctif complexe) et pour la règle
  d'invocation automatique vs explicite.
- **Si un skill n'est momentanément pas détecté** (dossier manquant, non repéré par le harnais),
  ne pas bloquer la tâche : continuer sans lui, mais signaler clairement son indisponibilité à
  l'utilisateur.

Détail complet des workflows, de l'invocation par agent et des documents liés :
[`docs/agents/skills-usage.md`](docs/agents/skills-usage.md).

## Spécificités Codex

- Pas de commandes slash : toujours nommer le skill explicitement dans l'instruction pour
  l'invoquer volontairement (les skills auto-invocables — `tdd`, `domain-modeling`,
  `codebase-design`, `code-review` — peuvent aussi se déclencher sans être nommés si la tâche le
  justifie clairement).
- `/setup-matt-pocock-skills` a été exécuté manuellement lors de l'installation initiale (pas de
  session interactive disponible) ; les choix retenus sont documentés dans
  `docs/agents/issue-tracker.md` et `docs/agents/domain.md`. Le relancer n'est utile que pour
  changer de gestionnaire de tickets ou repartir de zéro.
