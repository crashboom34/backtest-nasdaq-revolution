# Isolation du futur module Options comme sous-système séparé

**Statut** : Proposed (Proposé)
**Date** : 2026-08-06

## Contexte

L'utilisateur souhaite, à terme, un module options et produits dérivés (chaînes d'options,
Greeks, valorisation, stratégies multi-jambes). `docs/adr/0002-canonical-market-data-schema.md`
a déjà explicitement écarté le schéma complet à 20+ colonnes incluant les options pour le socle
Data Center Phase 1 ("aucun fournisseur ne produit encore ces champs"). Le moteur actuel
(`engine.py`, `strategies/perfect_revolution_v1.py`) est conçu pour un instrument spot unique
par backtest.

## Forces en présence

- Les options ont des invariants radicalement différents du spot (expiry, strike, exercice,
  assignation, Greeks) — les mélanger au moteur actuel créerait des cas spéciaux fragiles
  (branches conditionnelles ad hoc sur un même module pour deux logiques métier distinctes,
  un signe classique qu'une séparation de module est nécessaire).
- Le module options ne doit **jamais bloquer** le déploiement serveur ni la fiabilité
  scientifique du moteur spot (contrainte explicite de l'utilisateur).
- Les données d'options ont des sources hétérogènes à distinguer clairement : réellement
  historiques, capturées progressivement via IG à partir de maintenant, ou théoriques
  reconstruites (ex. Black-Scholes).

## Options évaluées

1. **Étendre le moteur spot actuel avec des branches conditionnelles pour les options** — rejeté :
   viole la profondeur des modules existants, fragilise le moteur validé pour le spot.
2. **Dépôt séparé** — rejeté pour l'instant : duplique l'infrastructure (Data Center, jobs,
   reporting) sans besoin réel identifié de déploiement indépendant.
3. **Sous-système séparé dans le même dépôt, avec ses propres types de domaine
   (OptionContract, OptionChain, OptionStrategy) et son propre moteur de valorisation, ne
   partageant que l'infrastructure générique (jobs, stockage, UI framework)** (retenu).

## Décision

Le module Options est un **sous-système isolé** : ses types de domaine, son moteur de
valorisation/simulation et ses données ne sont jamais mélangés à ceux du moteur spot. Il
réutilise l'infrastructure générique (file de travaux, stockage Parquet, UI) mais rien de la
logique métier spot. Les données d'options doivent toujours porter une étiquette explicite parmi
les 4 catégories : (1) historiques réelles, (2) capturées via IG à partir de maintenant, (3)
théoriques reconstruites, (4) backtest sur sous-jacent uniquement — jamais mélangées sans cette
distinction visible dans les résultats.

## Conséquences positives

- Le moteur spot actuel n'est jamais mis en danger par l'ajout des options.
- Le calendrier de développement du module Options peut glisser sans impacter les autres phases.

## Conséquences négatives

- Duplication partielle probable de certains concepts (ex. calendrier de marché, gestion du
  risque) entre spot et options — acceptée consciemment pour préserver l'isolation.

## Risques

Si l'isolation n'est pas respectée dès le départ, un couplage accidentel rendrait la séparation
coûteuse à défaire plus tard — mitigé en traitant toute tentative de partage de code au-delà de
l'infrastructure générique comme un signal à documenter en ADR avant de la faire.

## Plan de migration

Sans objet à ce stade (module non démarré) — cette ADR fixe la contrainte avant tout
développement (Phase 7).

## Critères de réévaluation

Si une vraie source de données d'options historiques fiable et abordable est identifiée, ou si
IG fournit un accès élargi aux options, réévaluer l'ampleur réaliste du module.
