# Index de la documentation d'architecture

Point d'entrée de la documentation d'architecture cible (mission de planification du 2026-08-06,
sans modification de code/données/serveur).

Ne duplique pas `README.md` (contexte fonctionnel), `AI_HANDOFF.md` (journal détaillé des
sessions de développement), `CONTEXT.md` (glossaire métier confirmé), `AGENTS.md`/`CLAUDE.md`
(instructions agents) — lire ces documents en premier si le contexte général manque.

## Architecture (`docs/architecture/`)

| Document | Contenu |
|---|---|
| [`CURRENT_STATE.md`](architecture/CURRENT_STATE.md) | État réel constaté par audit du 2026-08-06 — ce qui est implémenté, partiel, prévu non branché, absent, ou code mort. **À lire en premier.** |
| [`QUALITY_ATTRIBUTES.md`](architecture/QUALITY_ATTRIBUTES.md) | Attributs de qualité cibles (indépendance, parallélisme, reproductibilité, sécurité, etc.) et compromis assumés |
| [`TARGET_ARCHITECTURE.md`](architecture/TARGET_ARCHITECTURE.md) | Principes évalués, diagrammes C4 Contexte/Conteneurs/Composants |
| [`DEPLOYMENT_ARCHITECTURE.md`](architecture/DEPLOYMENT_ARCHITECTURE.md) | Diagrammes de déploiement (serveur unique, architecture évolutive), profils serveur |
| [`COMPUTE_AND_JOBS.md`](architecture/COMPUTE_AND_JOBS.md) | Comparaison des files de travaux, cycle de vie cible d'un job, concurrence |
| [`DATA_ARCHITECTURE.md`](architecture/DATA_ARCHITECTURE.md) | Flux de données cible, fin du pipeline Data Center, calendrier de marché |
| [`SECURITY_AND_OPERATIONS.md`](architecture/SECURITY_AND_OPERATIONS.md) | Modèle de menace, observabilité, CI/CD, sauvegarde et reprise après sinistre |
| [`UI_UX_ARCHITECTURE.md`](architecture/UI_UX_ARCHITECTURE.md) | Architecture de l'information, navigation cible, design system, migration progressive |
| [`TEST_AND_VALIDATION_ARCHITECTURE.md`](architecture/TEST_AND_VALIDATION_ARCHITECTURE.md) | Walk-forward, Monte-Carlo, out-of-sample, modèle d'exécution, règles Champion |
| [`DOMAIN_MODEL.md`](architecture/DOMAIN_MODEL.md) | Modèle de domaine cible (complète `CONTEXT.md` sans le dupliquer — concepts futurs, pas encore confirmés) |
| [`LINUX_PORTABILITY_REPORT.md`](architecture/LINUX_PORTABILITY_REPORT.md) | Audit de portabilité Linux (PH0-OCI-01) : compatibilité par catégorie, tests exécutés, corrections proposées, décision Go/No-Go |

## Roadmap (`docs/roadmap/`)

| Document | Contenu |
|---|---|
| [`MASTER_ROADMAP.md`](roadmap/MASTER_ROADMAP.md) | 9 phases (0 à 8), objectifs/critères/risques/effort par phase |
| [`DEPENDENCY_MAP.md`](roadmap/DEPENDENCY_MAP.md) | Carte des dépendances transversales entre chantiers |
| [`RISK_REGISTER.md`](roadmap/RISK_REGISTER.md) | Registre des risques (probabilité, impact, mitigation) |
| [`DECISION_BACKLOG.md`](roadmap/DECISION_BACKLOG.md) | Décisions ouvertes nécessitant preuve/prototype avant tranchage |
| [`EPICS_AND_TICKETS.md`](roadmap/EPICS_AND_TICKETS.md) | Epics par phase, tickets précis (Phases 0-1), tickets macroscopiques (Phases 2-8) |
| [`BENCHMARK_PLAN.md`](roadmap/BENCHMARK_PLAN.md) | Protocole de benchmark, profils serveur, repères de marché datés |

## ADR (`docs/adr/`)

ADR existants (0001-0004, statut Proposé, jamais renumérotés) + nouveaux ADR de cette mission :

| ADR | Titre | Statut |
|---|---|---|
| [0005](adr/0005-modular-monolith-with-separated-workers.md) | Monolithe modulaire avec workers séparés | Proposed (Proposé) |
| [0006](adr/0006-job-queue-technology.md) | Technologie de la file de travaux (RQ/Celery) | Decision pending (Décision en attente) |
| [0007](adr/0007-postgresql-for-metadata.md) | PostgreSQL pour les métadonnées | Proposed (Proposé) |
| [0008](adr/0008-market-data-storage-strategy.md) | Stockage des données de marché et provenance | Proposed (Proposé) |
| [0009](adr/0009-docker-compose-for-staging.md) | Docker Compose pour le staging | Proposed (Proposé) |
| [0010](adr/0010-app-py-decomposition.md) | Décomposition progressive de `app.py` | Proposed (Proposé) |
| [0011](adr/0011-options-module-isolation.md) | Isolation du module Options | Proposed (Proposé) |
| [0012](adr/0012-environments-local-staging-production.md) | Environnements Local/Staging/Production | Proposed (Proposé) |
| [0013](adr/0013-market-calendar-in-resampling.md) | Calendrier de marché dans le resampling | Proposed (Proposé) |
| [0014](adr/0014-strategy-authoring-python-vs-dsl.md) | Stratégies Python vs DSL | Decision pending (Décision en attente) |
| [0015](adr/0015-oracle-cloud-infrastructure-payg.md) | Oracle Cloud Infrastructure PAYG pour le staging et le calcul à la demande | Accepted (Accepté) |

## Comment naviguer

1. Nouveau sur le projet ou la mission ? Commencer par `CURRENT_STATE.md`, puis
   `TARGET_ARCHITECTURE.md`.
2. Préparer un déploiement ? `DEPLOYMENT_ARCHITECTURE.md` + `COMPUTE_AND_JOBS.md` +
   `BENCHMARK_PLAN.md` + [ADR 0015](adr/0015-oracle-cloud-infrastructure-payg.md) (Oracle Cloud,
   décision validée).
3. Travailler sur les données ? `DATA_ARCHITECTURE.md` + ADR 0008/0013.
4. Travailler sur l'UI ? `UI_UX_ARCHITECTURE.md` + ADR 0010.
5. Comprendre ce qui reste à décider ? `DECISION_BACKLOG.md`.
6. Démarrer une tâche concrète ? `EPICS_AND_TICKETS.md`, en respectant `DEPENDENCY_MAP.md`.
