# CLAUDE.md

Instructions pour **Claude Code** dans ce dépôt (`crashboom34/backtest-nasdaq-revolution`).
Ce fichier est le pendant Claude Code de `AGENTS.md` (lu par Codex) — les règles communes au
projet (méthodologie, sécurité, contraintes métier) doivent rester cohérentes entre les deux
fichiers ; voir `docs/agents/` pour la documentation partagée détaillée. Les sections propres aux
capacités, commandes, skills et outils de chaque agent peuvent en revanche différer d'un fichier
à l'autre — aucune commande Claude Code ne doit être copiée dans `AGENTS.md` sans vérifier au
préalable son équivalent réel dans Codex.

## À propos du projet

Application de backtest de stratégies de trading algorithmique (Streamlit), aujourd'hui centrée
sur l'indice US100 (NASDAQ) en timeframe M3, données MetaTrader 5. Voir `README.md` et
`AI_HANDOFF.md` pour le contexte fonctionnel détaillé, et `CONTEXT.md` pour le glossaire métier.

## Agent skills

Les [skills d'ingénierie de Matt Pocock](https://github.com/mattpocock/skills) sont installés
dans ce dépôt, en fichiers complets (pas seulement `SKILL.md`) :

- **Emplacement pour Claude Code** : `.claude/skills/<skill-name>/` — Claude Code détecte ces
  skills automatiquement depuis ce dossier projet ; utilise les commandes slash quand elles sont
  disponibles (ex. `/grill-with-docs`, `/to-spec`, `/implement`).
- **Emplacement pour Codex** : `.agents/skills/<skill-name>/` — Codex n'a pas de commandes
  slash ; le nom du skill doit être mentionné explicitement dans l'instruction.
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
- Claude Code (et Codex) doivent utiliser les skills disponibles lorsqu'ils correspondent à la
  tâche en cours — voir `docs/agents/skills-usage.md` pour les enchaînements recommandés
  (nouvelle fonctionnalité, amélioration d'architecture, correctif complexe) et pour la règle
  d'invocation automatique vs explicite.
- **Si un skill n'est momentanément pas détecté** (dossier manquant, non repéré par le harnais),
  ne pas bloquer la tâche : continuer sans lui, mais signaler clairement son indisponibilité à
  l'utilisateur.

Détail complet des workflows, de l'invocation par agent et des documents liés :
[`docs/agents/skills-usage.md`](docs/agents/skills-usage.md).

## Politique obligatoire de sélection des skills, plugins, MCP et outils

> Cette section est spécifique à Claude Code. Les noms de skills, commandes slash, outils
> natifs et MCP décrits ici ne doivent pas être supposés disponibles dans Codex ou dans un autre
> agent — une politique équivalente pour Codex, auditée séparément dans `AGENTS.md`, fait l'objet
> d'une tâche distincte.

Les capacités utiles ne se trouvent pas toutes dans `.claude/skills/` : skills projet, skills
personnelles (`~/.claude/`), plugins (`~/.claude/plugins/installed_plugins.json`), skills
intégrées à Claude Code, MCP connectés, outils natifs, commandes slash. Ne jamais supposer
qu'une capacité existe parce que son nom est mentionné dans une instruction — vérifier dans la
session. `.agents/skills/` (Codex) sert uniquement de comparaison, non invocable ici. Le détail
de chaque skill projet reste dans son propre `SKILL.md` — ce fichier ne fait que router.

### 1. Analyser puis sélectionner

Avant chaque tâche, examiner les capacités réellement disponibles (le tableau ci-dessous peut
devenir obsolète — revérifier au doute) et ne choisir que celles utiles. Généralement une à
trois capacités ; plus pour une mission complexe, jamais par défaut ni par redondance (pas deux
skills au même rôle sans raison, pas de skill sur une tâche triviale).

### 2. Invoquer réellement

Une capacité retenue doit être réellement appelée avec son nom exact — jamais seulement
mentionnée ou annoncée sans appel. Aucune commande slash inventée (`/playwright`,
`/superpowers`, `/kaizenkaizen`, "Codex Orchestrator" n'existent pas ici).

### 3. Transparence

En début de tâche : `Capacités sélectionnées : /tdd, /code-review` (ou
`Capacités sélectionnées : aucune capacité spécialisée nécessaire`). En fin de tâche : lister ce
qui a réellement été invoqué (skills, plugins, MCP, outils) et toute capacité voulue mais
indisponible.

### 4. Tableau de routage

| Capacité | Nom exact | Type | Quand |
|---|---|---|---|
| Revue finale | `code-review` | Skill projet, auto | Qualité, sécurité, régression, conformité avant commit/PR |
| Conception de module | `codebase-design` | Skill projet, auto | Nouvelle architecture/sous-système, interface d'un module |
| Modèle métier | `domain-modeling` | Skill projet, auto | Entités, règles, invariants, glossaire/ADR |
| TDD | `tdd` | Skill projet, auto | Bug, changement de comportement, feature testable |
| Implémentation | `implement` | Skill projet, auto | Mise en œuvre d'une tâche déjà spécifiée |
| Refactor architecture existante | `improve-codebase-architecture` | Skill projet, auto | Dette technique sur du code déjà là (≠ conception neuve) |
| Rédaction de spec | `to-spec` | Skill projet, auto | Besoin déjà discuté → spec écrite |
| Découpage en tickets | `to-tickets` | Skill projet, auto | Spec déjà validée → tâches exécutables |
| Setup tracker | `setup-matt-pocock-skills` | Skill projet, manuel | Uniquement pour changer de tracker |
| Interview de conception | `grill-with-docs` | Skill projet, manuel | Affûter un plan déjà proposé (interview + ADR) — **pas** une vérification de doc API externe |
| Nettoyage ciblé | `simplify` | Skill intégré, auto | Réutilisation/simplification/efficacité d'un diff local, jamais une refonte générale — substitut de "kaizenkaizen" (absent) |
| Méthode structurée | `superpower` (+ `debug`/`brainstorm`/`plan`/`verify`/`worktree`) | Skill intégré, auto | Mission complexe nécessitant une méthode ; jamais "superpowers" |
| Design UI/UX | `ui-ux-pro-max` | Skill personnel, auto | Interface, ergonomie, accessibilité, direction visuelle — jamais pour du backend pur |
| Doc officielle externe | `WebSearch`/`WebFetch` (+ MCP officiel du fournisseur si un existe) | Outil natif | Vérifier un endpoint/format IG/EODHD réel, jamais deviné — puis `tdd`/`implement`/`code-review` selon besoin |
| Outils EODHD | `mcp__plugin_eodhd-api_eodhd__*` | MCP (plugin `eodhd-api`) | Vérifier un endpoint EODHD avant de coder — jamais une dépendance runtime |
| Validation UI de ce projet | bibliothèque `playwright` (`.venv`) | Outil natif (lib projet) | Script `Bash`, canal `msedge` — pas de skill/MCP Playwright ici |
| Orchestration | `Agent` / `Workflow` | Outils natifs | Mission longue/multi-étapes — substitut de "Codex Orchestrator" (absent) |
| GitHub | `gh` (CLI) | Outil natif | Convention du projet pour toute opération GitHub |
| MCP `n8n` | — | MCP configuré, indisponible | Aucun outil résolu ; signaler si sollicité, ne pas bloquer |

### 5. Distinguer skill / plugin / MCP / outil

Skill = invocable par nom (souvent `/nom`), projet (`.claude/skills/`), personnel
(`~/.claude/skill.md`) ou intégré à Claude Code. Plugin = skills/outils namespacés
`plugin:nom` venant d'un plugin installé. MCP = outil `mcp__serveur__action` d'un serveur
configuré, appelé directement, jamais via un faux slash. Outil natif = `Read`/`Edit`/`Grep`/
`Bash`/`WebFetch`/`WebSearch`/`Agent`/`Workflow`/`gh`/bibliothèques du projet (ex. `playwright`).

### 6. Capacité indisponible

Ne jamais bloquer ni inventer une utilisation. Continuer avec les outils disponibles et signaler
clairement l'indisponibilité dans le compte rendu.

### 7. Règles de sécurité toujours applicables

Lire `README.md`/`AI_HANDOFF.md`/`CONTEXT.md`/`AGENTS.md` quand pertinent ; `git status --short`
avant modification ; aucun secret affiché/versionné ; aucun commit ni push sans autorisation
explicite à chaque fois ; aucun téléchargement massif sans autorisation ; jamais modifier
`app_corrupted_backup.py` ; aucune opération ou ordre IG live.

## Spécificités Claude Code

- Utiliser les commandes slash des skills quand elles existent plutôt que de reformuler
  l'instruction en texte libre.
- `/setup-matt-pocock-skills` a été exécuté manuellement lors de l'installation initiale (pas de
  session interactive disponible) ; les choix retenus sont documentés dans
  `docs/agents/issue-tracker.md` et `docs/agents/domain.md`. Le relancer n'est utile que pour
  changer de gestionnaire de tickets ou repartir de zéro.
