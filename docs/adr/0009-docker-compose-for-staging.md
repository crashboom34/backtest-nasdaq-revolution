# Docker Compose pour la première version serveur (staging)

**Statut** : Proposed (Proposé)
**Date** : 2026-08-06

## Contexte

Aucun artefact d'infrastructure n'existe aujourd'hui dans le dépôt (audit du 2026-08-06 :
absence confirmée de `.github/workflows/`, `Dockerfile`, `docker-compose.yml`, config
Redis/PostgreSQL). `requirements-server.txt` existe déjà et retire `metatrader5` — bonne base de
départ pour un environnement Linux. La portabilité Linux du cœur applicatif est meilleure que
redouté (aucune dépendance Windows dure dans `app.py`/`engine.py`/l'orchestration).

## Forces en présence

- Le premier serveur cible est un serveur unique (Phase 1) — pas encore un cluster.
- L'objectif est un déploiement simple, compréhensible, reproductible par un futur agent Claude
  Code/Codex sans connaissance implicite.
- Kubernetes serait disproportionné pour un serveur unique mono-utilisateur.

## Options évaluées

1. **Installation manuelle directe sur le serveur** (sans conteneurs) — rejeté : pas reproductible,
   dérive de configuration difficile à auditer/rollback.
2. **Kubernetes** — rejeté pour la Phase 1 : complexité et coût opérationnel disproportionnés
   pour un serveur unique.
3. **Docker Compose** (retenu) — reproductible, simple à auditer (un seul fichier), bon support
   pour interface + workers + Redis + PostgreSQL + reverse proxy sur une seule machine, migration
   naturelle vers de l'orchestration plus riche si le besoin apparaît (Phase 2 architecture
   évolutive multi-nœuds).

## Décision

Utiliser **Docker Compose** pour la Phase 1 (serveur de staging unique) : un service par
composant (interface Streamlit, orchestrateur, workers, Redis, PostgreSQL, reverse proxy). Les
données de marché et les résultats de jobs vivent sur un volume monté, jamais dans l'image.
Aucun secret dans l'image ni dans le dépôt — variables d'environnement ou fichier `.env` non
versionné, injecté au démarrage du service.

## Conséquences positives

- Reproductible depuis GitHub + ce fichier Compose ; redéploiement rapide après incident.
- Chaque composant remplaçable indépendamment (ex. changer de reverse proxy) sans casser les
  autres.

## Conséquences négatives

- Ajoute une couche de conteneurisation à apprendre/maintenir si l'équipe ne la connaît pas déjà.
- Docker Compose seul ne gère pas la haute disponibilité multi-nœuds — acceptable en Phase 1,
  réévalué en Phase 2.

## Risques

Image Docker non maintenue (dépendances non mises à jour) — mitigé par une politique de
reconstruction régulière et de scan de vulnérabilités (voir `SECURITY_AND_OPERATIONS.md`).

## Plan de migration

1. `docker-compose.yml` de staging avec les services listés dans
   [`DEPLOYMENT_ARCHITECTURE.md`](../architecture/DEPLOYMENT_ARCHITECTURE.md) (le fichier
   `docker-compose.yml` lui-même reste à créer en Phase 1 — non fait dans cette mission
   d'architecture).
2. Validation manuelle du déploiement staging avant toute promotion en production.
3. Réévaluation d'un orchestrateur plus riche seulement si un besoin multi-nœuds réel apparaît.

## Critères de réévaluation

Si plusieurs nœuds workers deviennent nécessaires simultanément avec un besoin de répartition de
charge dynamique, réévaluer un orchestrateur plus riche (ex. Nomad, Kubernetes allégé).
