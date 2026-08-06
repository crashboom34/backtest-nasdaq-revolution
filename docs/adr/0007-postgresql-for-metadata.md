# PostgreSQL pour les métadonnées applicatives

**Statut** : Proposed (Proposé)
**Date** : 2026-08-06

## Contexte

Aujourd'hui, toute la persistance est fichier (constat `CONTEXT.md`, confirmé par audit du
2026-08-06 : "aucune base de données trouvée"). Le catalogue (`settings/data_catalog.json`) est
même du code mort en pratique — sa persistance n'a aucun appelant en production, seule la
construction en mémoire (`catalog.build_catalog()`) est utilisée. À mesure que le système évolue
vers plusieurs workers, un futur multi-utilisateur, et un suivi fin des jobs/catalogues, la
persistance fichier plate atteint ses limites (pas de requêtes, pas de contraintes, pas de
concurrence sûre en écriture).

## Forces en présence

- Le job directory (fichiers) reste l'artefact portable de référence — ne doit pas migrer vers
  la base de données (voir ADR 0005 : contrat préservé).
- Les métadonnées candidates à une base de données sont : catalogue d'instruments/fournisseurs,
  index des jobs (au-delà du simple parcours disque actuel), configuration utilisateur future,
  registre IG (produits, historisation de spreads — actuellement absent), audit.
- Aucun besoin actuel de requêtes analytiques complexes sur les données de marché elles-mêmes
  (celles-ci restent en Parquet, voir ADR 0008).

## Options évaluées

1. **Rester 100% fichiers** — rejeté à terme : pas de contraintes d'intégrité, écretures
   concurrentes fragiles pour un catalogue partagé multi-workers.
2. **SQLite** — plus simple à opérer, mais faible en écriture concurrente multi-process/
   multi-workers, migration ultérieure vers un serveur plus difficile.
3. **PostgreSQL auto-hébergé** — riche, standard, bon support Docker Compose, migration facile
   vers un service managé plus tard.
4. **PostgreSQL managé (cloud)** — reporté : coût et choix d'hébergeur non tranchés
   (voir `docs/roadmap/DECISION_BACKLOG.md`).

## Décision

Adopter **PostgreSQL** pour les métadonnées applicatives (catalogue de données, index des jobs,
registre IG, configuration, audit), **jamais** pour les données de marché elles-mêmes (Parquet,
ADR 0008) ni pour le job directory (fichiers, ADR 0005). Auto-hébergé en Docker Compose pour la
Phase 1 (staging) ; le choix managé vs auto-hébergé en production reste en
`docs/roadmap/DECISION_BACKLOG.md`.

## Conséquences positives

- Le catalogue devient une source de vérité unique et interrogeable (fin de la dualité
  `catalog.py`/`unified_catalog.py`/fichier JSON mort constatée par l'audit).
- Prépare le registre IG (produits, historique de spreads) demandé dans la feuille de route.
- Facilite l'évolution multi-utilisateur (Phase 8) sans nouvelle refonte de stockage.

## Conséquences négatives

- Nouvelle dépendance d'infrastructure à sauvegarder, superviser, migrer (schéma).
- Nécessite une couche de migration de schéma (ex. Alembic) — à spécifier en Phase 1.

## Risques

Corruption ou perte de la base sans sauvegarde testée (voir `docs/architecture/SECURITY_AND_OPERATIONS.md`) — mitigé par une procédure de restauration testée dès la Phase 1.

## Plan de migration

1. Schéma initial minimal (catalogue, index de jobs, registre IG) en Phase 1.
2. Migration du contenu utile de `settings/data_catalog.json` si encore pertinent au moment de
   la bascule (sinon reconstruction depuis le disque).
3. Aucune donnée de marché ni artefact de job ne migre vers PostgreSQL.

## Critères de réévaluation

Si le volume de métadonnées reste trivial après plusieurs mois de staging, réévaluer si
PostgreSQL est encore justifié par rapport à SQLite.
