# Stratégies : Python uniquement, DSL, ou modèle hybride

**Statut** : Decision pending (Décision en attente)
**Date** : 2026-08-06

## Contexte

`strategies/perfect_revolution_v1.py` est aujourd'hui la seule stratégie, écrite en Python pur,
avec un contrat duck-typing (`reset/prepare/on_bar`) et un `PARAM_SCHEMA` déjà utilisé pour
générer dynamiquement l'UI de paramétrage. Le système de découverte dynamique
(`glob.glob("strategies/*.py")`) accueille déjà plusieurs stratégies sans câblage en dur. Aucun
éditeur de stratégies sans code n'existe. Aucun prototype de DSL n'a été testé.

## Forces en présence

- Le contrat `Strategy` actuel (Python) est simple, performant (indicateurs pré-calculés en
  NumPy dans `prepare()`), et déjà validé par la stratégie existante.
- Un DSL JSON/YAML apporterait une création sans code (objectif explicite de l'utilisateur), mais
  pose la question de la sécurité (exécuter des règles définies par un utilisateur sans
  `eval()`/`exec()` non sandboxé) et de l'expressivité (toute logique Python n'est pas
  facilement traduisible en règles ET/OU déclaratives).
- Ce chantier vient explicitement **après** la fiabilité du moteur (Phase 6, après Phase 3) —
  aucune urgence à trancher maintenant.

## Options évaluées

1. **Python uniquement** — le plus simple à maintenir, pas de nouvelle couche de compilation,
   mais aucune création de stratégie sans écrire de code.
2. **DSL JSON/YAML complet, compilé vers une représentation exécutable sûre** — répond au besoin
   sans-code, mais coût de conception (grammaire, validations, sandboxing) et risque de ne pas
   couvrir tous les cas que Python couvre nativement (ex. logique complexe multi-état).
3. **Modèle hybride** (DSL pour les cas courants ET/OU/stops/objectifs/sizing, Python pour les
   cas avancés) — couvre plus de cas, mais duplique la logique de contrat entre deux systèmes.

## Décision

**Aucune décision définitive.** Cette ADR documente le choix à trancher en Phase 6, une fois la
fiabilité scientifique du moteur (Phase 3) établie. Les critères de décision : (a) la majorité
des stratégies envisagées sont-elles exprimables en règles ET/OU simples ? (b) le coût de
sandboxing d'un DSL est-il acceptable au regard du bénéfice utilisateur réel ? (c) un prototype
DSL minimal reproduit-il fidèlement `perfect_revolution_v1.py` ?

## Conséquences positives

Ne pas trancher maintenant évite d'investir dans un DSL avant d'avoir un moteur validé
scientifiquement sur lequel s'appuyer.

## Conséquences négatives

Le contrat `Strategy` (Python) pourrait devoir évoluer rétroactivement si un DSL est retenu plus
tard — risque accepté, documenté.

## Risques

Un DSL mal sécurisé (évaluation de règles utilisateur) pourrait introduire une surface
d'attaque — à traiter comme un sujet de sécurité de première classe si cette option est retenue
(voir `docs/architecture/SECURITY_AND_OPERATIONS.md`).

## Plan de migration

Sans objet tant que la décision n'est pas prise (Phase 6).

## Critères de réévaluation

Réévaluer dès qu'un prototype DSL minimal existe et peut être comparé objectivement au contrat
Python actuel sur la stratégie de référence.
