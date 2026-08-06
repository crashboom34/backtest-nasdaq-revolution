# Technologie de la file de travaux (jobs)

**Statut** : Decision pending (Décision en attente)
**Date** : 2026-08-06

## Contexte

L'ADR 0005 décide qu'une file de travaux remplace le lancement direct de `subprocess.Popen`
pour distribuer les backtests/optimisations sur des workers séparés. Il reste à choisir la
technologie. Le système actuel (`optimization_store.py`, verrou `assert_no_active_jobs()`,
fichiers `progress.json`/`tested.json`/`stop.flag`) doit continuer de fonctionner pendant la
transition — aucune preuve de performance comparative n'existe encore dans ce dépôt.

## Forces en présence

- Windows (poste de développement actuel) et Linux (serveur cible) doivent tous deux être
  supportés au moins pendant la phase de transition.
- Le besoin réel (annulation, suivi de progression fin, reprise après crash) dépasse une simple
  file FIFO : `resume_run_id`/`tested.json` existent déjà côté moteur mais ne sont jamais
  déclenchés automatiquement (constat d'audit du 2026-08-06).
- Aucun prototype ni benchmark n'a encore été réalisé sur ce dépôt.

## Options évaluées

1. **Multiprocessing local seul (statu quo)** — le plus simple, mais ne distribue pas sur
   plusieurs machines et ne resiste pas à un redémarrage de l'hôte.
2. **Redis + RQ** — plus simple à opérer que Celery, bon suivi de job intégré, communauté plus
   restreinte, moins de fonctionnalités avancées (retries complexes, workflows).
3. **Redis + Celery** — plus riche (retries, workflows, priorités, tâches périodiques), plus
   complexe à configurer et déboguer, empreinte opérationnelle plus lourde.
4. **Autre file simple** (ex. base de données comme file — "poor man's queue") — évite une
   dépendance supplémentaire, mais réinvente des mécanismes déjà fournis par RQ/Celery.

## Décision

**Aucune décision définitive.** Un prototype/benchmark est requis avant de trancher entre RQ et
Celery (voir `docs/roadmap/BENCHMARK_PLAN.md`, section file de travaux). Le prototype doit
mesurer : complexité de mise en place, fiabilité de reprise après crash, qualité du suivi de
progression, annulation, priorité, compatibilité Windows (dev) / Linux (serveur), coût de
maintenance. Le format de job directory doit être préservé quelle que soit l'option retenue.

## Conséquences positives

Reporter la décision évite un choix technologique irréversible avant d'avoir des preuves.

## Conséquences négatives

La Phase 1 (serveur de staging) devra définir une option par défaut pour ne pas être bloquée —
recommandation : démarrer avec **RQ** en staging (plus simple), garder Celery en option de
réévaluation si des besoins avancés (workflows multi-étapes, tâches périodiques) apparaissent.

## Risques

Changer de technologie après une adoption large en production aurait un coût de migration non
négligeable (code d'orchestration, supervision, déploiement) — d'où l'intérêt du prototype avant
adoption large.

## Plan de migration

1. Prototype RQ vs Celery sur un scénario représentatif (voir `BENCHMARK_PLAN.md`).
2. Décision tranchée, ADR mis à jour en statut Accepted avec le choix retenu et les preuves.
3. Bascule progressive : job directory inchangé, seul le déclenchement change.

## Critères de réévaluation

Dès que le prototype de la Phase 1 produit des résultats mesurés (voir `BENCHMARK_PLAN.md`).
