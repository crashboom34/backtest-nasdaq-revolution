# Utilisation conjointe de Claude Code et Codex avec un socle de skills et de documentation partagé

Status: Proposé

Ce dépôt est destiné à être ouvert alternativement avec Claude Code et avec Codex (et
potentiellement Claude Cowork). Pour que les deux agents travaillent de façon cohérente sans
réinstallation ni documentation divergente, nous avons décidé :

- d'installer les dix skills d'ingénierie de Matt Pocock (`mattpocock/skills`) en fichiers complets
  (pas seulement `SKILL.md`) à deux emplacements — `.claude/skills/` pour Claude Code et
  `.agents/skills/` pour Codex — avec un contenu strictement identique entre les deux ;
- de partager un unique modèle de domaine mono-contexte (`CONTEXT.md` à la racine) plutôt qu'une
  documentation par agent ;
- d'exiger une cohérence obligatoire entre `AGENTS.md` (Codex) et `CLAUDE.md` (Claude Code) : les
  informations communes (skills, modèle de domaine, gestionnaire de tickets, ADR) doivent être
  identiques ou clairement synchronisées entre les deux fichiers, chacun ne conservant que ses
  règles propres à son agent ;
- de conserver les skills dans le dépôt lui-même (et non dans un emplacement utilisateur hors
  dépôt), pour qu'ils suivent le code et soient versionnés avec lui.

## Considered Options

- **Un seul emplacement de skills partagé par lien symbolique.** Rejeté pour l'instant : les liens
  symboliques posent des problèmes de portabilité sur Windows (droits administrateur / mode
  développeur requis) et de fiabilité selon l'outil Git utilisé. Deux copies identiques, avec un
  contrôle de cohérence (`diff -rq`), ont été préférées le temps qu'une convention unique émerge
  entre les outils.
- **Plugin Claude Code officiel (`claude plugins install`) au lieu de fichiers copiés dans le
  dépôt.** Rejeté : un plugin géré par Claude Code seul ne serait pas visible par Codex, qui n'a
  pas encore de plugin natif équivalent (voir la note du dépôt source à ce sujet).

## Consequences

- Toute modification manuelle d'un skill doit être répercutée dans les deux dossiers
  (`.claude/skills/<skill>` et `.agents/skills/<skill>`), ou re-synchronisée via
  `npx skills@latest update`, sous peine de divergence silencieuse entre agents.
- Ce choix pourra être révisé si `mattpocock/skills` publie un jour un plugin Codex natif dédié
  (mentionné comme feuille de route dans le dépôt source), ce qui permettrait de retirer la copie
  dupliquée.
