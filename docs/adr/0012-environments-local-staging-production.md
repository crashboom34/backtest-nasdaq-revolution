# Environnements Local / Staging / Production et politique de promotion

**Statut** : Proposed (Proposé)
**Date** : 2026-08-06

## Contexte

Aujourd'hui, un seul environnement existe : le poste Windows local de l'utilisateur. Aucune
distinction staging/production n'existe dans le dépôt (pas de CI, pas de config
d'environnement multiple constatée par l'audit du 2026-08-06). `path_resolver.py` gère déjà
`BACKTEST_BASE_DIR` par variable d'environnement — bonne base pour distinguer les environnements
sans dupliquer le code.

## Forces en présence

- IG démo (jamais live) et EODHD sont déjà gérés par variables d'environnement
  (`BACKTEST_IG_ENVIRONMENT=demo` obligatoire, clés API en variables d'env) — le mécanisme de
  séparation par environnement existe déjà partiellement.
- Le risque de tester une modification directement en production (perte de données, corruption
  de résultats en cours) doit être éliminé structurellement, pas seulement par discipline.

## Options évaluées

1. **Un seul environnement serveur** (rejeté) — aucune façon sûre de valider un changement avant
   qu'il n'affecte les jobs/données réels.
2. **Local + Production seulement** (rejeté) — pas d'endroit pour valider un déploiement complet
   (Docker Compose, migrations, secrets) avant la production.
3. **Local + Staging + Production** (retenu) — conforme à la demande explicite de l'utilisateur.

## Décision

Trois environnements : **Local** (poste de développement, Windows ou Linux, données réduites),
**Staging** (serveur de calcul réel, Phase 1, données représentatives, IG démo uniquement),
**Production** (si et quand décidée — voir `docs/roadmap/DECISION_BACKLOG.md`, commercialisation
non engagée). Chaque environnement a ses propres secrets (jamais partagés), sa propre base
PostgreSQL, son propre volume de données. Aucune modification n'est testée directement en
production. La promotion staging → production nécessite une approbation manuelle explicite
(voir `docs/architecture/SECURITY_AND_OPERATIONS.md` et CI/CD).

## Conséquences positives

- Un changement risqué (ex. nouvelle version du moteur de jobs) est validé en conditions réelles
  avant d'affecter des données de production.
- Cohérent avec la politique déjà en vigueur "IG démo uniquement, jamais de live".

## Conséquences négatives

- Coût de duplication d'infrastructure (2 à 3 jeux de secrets, bases, volumes) — acceptable vu la
  criticité (aucune perte de données de production tolérée).

## Risques

Dérive de configuration entre staging et production si elles ne sont pas définies par le même
mécanisme (Docker Compose + variables d'environnement) — mitigé en gardant un seul
`docker-compose.yml` paramétré par environnement, jamais deux configurations divergentes
maintenues manuellement.

## Plan de migration

1. Phase 1 : Staging seul, pas de Production tant que la commercialisation n'est pas décidée.
2. Production introduite uniquement si Phase 8 est engagée.

## Critères de réévaluation

Si le projet reste strictement mono-utilisateur sans commercialisation, réévaluer si un
environnement Production distinct de Staging apporte une valeur réelle.
