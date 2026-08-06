# Stratégie de stockage des données de marché (raw immuable / normalisé / dérivé, provenance obligatoire)

**Statut** : Proposed (Proposé)
**Date** : 2026-08-06

## Contexte

L'audit du 2026-08-06 (détail complet dans [`CURRENT_STATE.md` §4](../architecture/CURRENT_STATE.md))
constate un stockage hétérogène : Parquet **uniquement** pour les snapshots EODHD normalisés ;
JSON pour le brut EODHD et les manifestes ; CSV pour les sources locales et le cache de
timeframes dérivés. Les champs de provenance (`snapshot_id`/`content_hash`/`period_start`/
`period_end`) existent dans `BacktestManifest` mais sont **vides pour 100 % des manifestes
produits aujourd'hui** — le seul appelant en production (`job_store.write_data_manifest()`) ne
relie jamais le vrai hash EODHD au manifeste de backtest.

## Forces en présence

- ADR 0002 fixe déjà le schéma canonique minimal OHLCV — cette ADR ne le remet pas en cause.
- ADR 0003/0004 fixent déjà les règles de resampling — cette ADR ne les remet pas en cause
  (voir ADR 0013 pour l'intégration du calendrier).
- Le contrat CSV historique (`nasdaq_3m.csv`, `data/{ASSET}/{TIMEFRAME}/`) doit rester lisible
  tel quel — aucune migration forcée des données existantes.
- Un volume NVMe dédié aux données (hors code) est un objectif déjà exprimé par l'utilisateur.

## Options évaluées

1. **Statu quo** (CSV + Parquet mélangés) — rejeté à terme : empêche une politique de
   rétention/sauvegarde uniforme, et la provenance reste non fiable.
2. **Tout migrer vers une base de données** — rejeté : les séries temporelles OHLCV sont bien
   plus efficacs en colonnaire (Parquet) qu'en base relationnelle pour ce volume.
3. **Uniformiser sur Parquet pour tout le normalisé/dérivé, JSON pour le brut immuable et les
   manifestes, CSV conservé uniquement en compatibilité pour les sources historiques déjà
   importées** (retenu).

## Décision

1. **Toute nouvelle donnée normalisée ou dérivée** (quel que soit le fournisseur) est stockée en
   **Parquet**, avec la même convention de nommage par `content_hash` qu'EODHD aujourd'hui.
2. Le **brut reste immuable** (JSON ou format natif du fournisseur), jamais réécrit.
3. **Tout manifeste de backtest doit porter un `snapshot_id`/`content_hash`/période réels** —
   `job_store.write_data_manifest()` doit être corrigé pour relier le vrai hash de la source
   utilisée (EODHD ou CSV local), quel que soit le chemin de données. Un manifeste sans hash
   réel devient une anomalie de qualité à signaler, pas un défaut silencieux accepté.
4. Les CSV historiques déjà importés (`nasdaq_3m.csv`, `data/{ASSET}/{TIMEFRAME}/`) restent lus
   tels quels par compatibilité, mais une politique de hash à la lecture est ajoutée pour leur
   donner, eux aussi, un `content_hash` réel dans le manifeste.
5. Toutes les données (brut, normalisé, dérivé) vivent sur le **volume NVMe dédié**, séparé du
   code — jamais dans le dépôt Git.

## Conséquences positives

- Provenance fiable pour toute stratégie qui devient "Champion" (condition de fiabilité
  scientifique, voir `docs/architecture/TEST_AND_VALIDATION_ARCHITECTURE.md`).
- Format de stockage cohérent, propice à des lectures rapides pour de gros volumes (1M+
  bougies) et à une politique de rétention/sauvegarde uniforme.

## Conséquences négatives

- Nécessite de corriger `job_store.write_data_manifest()` (changement de code, hors périmètre de
  cette mission d'architecture — à planifier en Phase 2, ticket dédié).
- Ajoute une étape de hash à la lecture des CSV historiques (léger coût CPU/E-S au premier accès).

## Risques

Un volume de données NVMe corrompu ou perdu sans sauvegarde est irremplaçable pour les données
achetées/téléchargées avec quota limité (EODHD) — voir `SECURITY_AND_OPERATIONS.md`.

## Plan de migration

1. Ne rien casser : les chemins CSV actuels continuent de fonctionner.
2. Ajouter le hash réel au manifeste (ticket Phase 2), sans changer le format des CSV existants.
3. Migrer le cache de timeframes dérivés (`derived_data/`, aujourd'hui CSV) vers Parquet au fil
   de l'eau, pas en un seul big-bang.

## Critères de réévaluation

Si le volume de données dépasse ce qu'un stockage fichier/Parquet gère confortablement (plusieurs To, besoin de requêtes transversales complexes), réévaluer un entrepôt colonnaire dédié (ex. DuckDB sur Parquet, ou solution analytique).
