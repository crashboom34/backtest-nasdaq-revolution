# Monolithe modulaire avec séparation interface / orchestration / workers de calcul

**Statut** : Proposed (Proposé)
**Date** : 2026-08-06

## Contexte

L'application actuelle est un monolithe Streamlit unique (`app.py`, 6 416 lignes, 126 fonctions,
7 onglets dont un à 10 sous-onglets — chiffres constatés par audit du 2026-08-06). Deux modèles
d'exécution coexistent déjà et sont incompatibles à terme :

- Le **backtest simple** s'exécute en process, de façon synchrone, dans le thread du serveur
  Streamlit (`app.py` → `engine.run_backtest()` directement) — bloque le rendu pendant le calcul.
- L'**optimisation** s'exécute déjà dans un process séparé (`subprocess.Popen` vers
  `optimizer_process.py`), lui-même parallélisé en interne par `ProcessPoolExecutor`.

Un seul job peut être actif à la fois (`job_launcher.assert_no_active_jobs()`), et rien ne
distribue le calcul sur plusieurs machines. L'ordinateur de l'utilisateur limite déjà la vitesse
des optimisations. Le contrat de sortie d'un job (détail complet dans
[`CURRENT_STATE.md` §1](../architecture/CURRENT_STATE.md)) doit être préservé quelle que soit
l'évolution de l'exécution.

## Forces en présence

- Le code de calcul (`engine.py`, `optimizer.py`, `scoring.py`) est déjà découplé de Streamlit
  par construction (aucun `import streamlit` dans ces modules).
- `job_launcher.py`/`optimizer_process.py` forment déjà une frontière process réelle,
  réutilisée à l'identique par l'UI et par `run_job.py` (CLI) — bon point de départ.
- Le besoin immédiat (ordinateur local trop lent) pousse vers plusieurs workers, potentiellement
  sur une autre machine — pas seulement plusieurs process locaux.
- Le risque de sur-ingénierie est réel : le projet est mono-utilisateur aujourd'hui ; une
  architecture microservices serait disproportionnée.

## Options évaluées

1. **Statu quo amélioré** : garder `subprocess.Popen` local, augmenter seulement le nombre de
   workers `ProcessPoolExecutor`. Rejeté seul — ne résout pas "je ferme mon navigateur"/serveur
   distant/redémarrage, et reste borné à une seule machine.
2. **Microservices complets** (API Gateway, service par domaine, mesh). Rejeté — complexité et
   coût d'exploitation disproportionnés pour un produit mono-utilisateur en phase
   d'industrialisation.
3. **Monolithe modulaire avec workers séparés par une file de travaux** (retenu) : une seule
   base de code, des frontières de module strictes (interface / orchestration / moteur /
   données), le calcul sort du process de l'interface via une file de travaux, des workers
   consomment cette file, potentiellement sur des machines différentes de l'interface.

## Décision

Adopter un **monolithe modulaire** : Streamlit reste l'interface, jamais le moteur d'exécution.
L'orchestration (aujourd'hui `job_launcher.py`/`optimizer_process.py`) devient la frontière
stable entre interface et calcul ; elle est étendue pour publier des travaux sur une file
(voir ADR 0006) au lieu de lancer directement un `subprocess.Popen` local. Le moteur de calcul
(`engine.py`, `optimizer.py`, `scoring.py`) ne change pas de responsabilité, seulement son mode
de déclenchement. Le contrat de fichiers du job directory est conservé à l'identique.

## Conséquences positives

- Le calcul peut s'exécuter sur une autre machine que l'interface, sans changer le moteur.
- Le format de job directory existant reste l'artefact portable de référence — aucune
  régression pour l'historique de jobs déjà produit.
- Migration progressive possible : la file de travaux peut d'abord tourner sur la même machine
  que l'interface (staging), puis se distribuer.

## Conséquences négatives

- Ajoute une brique d'infrastructure (file de travaux) et son cycle de vie à exploiter.
- Le mode "backtest simple" synchrone en process devra, à terme, aussi passer par ce mécanisme
  pour rester cohérent — sujet non tranché ici (voir `docs/roadmap/DECISION_BACKLOG.md`).

## Risques

- Complexité prématurée si le besoin réel reste mono-machine pendant longtemps — mitigé en
  gardant la file de travaux optionnelle en local (voir ADR 0006, statut "Decision pending").

## Plan de migration

1. Garder le contrat de job directory identique.
2. Introduire la file de travaux en local d'abord (un seul serveur de staging).
3. Ne migrer le "backtest simple" que si un besoin réel de non-blocage apparaît.

## Critères de réévaluation

Réévaluer si le besoin reste strictement mono-utilisateur/mono-machine après le premier
déploiement de staging (Phase 1) — la file de travaux distribuée pourrait alors être repoussée.
