# Intégration du calendrier de marché dans le rééchantillonnage (amendement à l'ADR 0003)

**Statut** : Proposed (Proposé)
**Date** : 2026-08-06

## Contexte

ADR 0003 fixe explicitement un ancrage **UTC uniquement, sans calendrier de marché** pour le
resampling M/H/D, en reportant ce sujet à une évolution séparée. `market_data/eodhd/calendar.py`
(`ExchangeCalendar`, `is_trading_day()`) existe depuis le 2026-08-06, mais audit confirmé : **non
utilisé par `market_data/resample.py`**, et son seul point de branchement
(`quality.detect_missing_trading_days()`) n'a aucun appelant en production. `CONTEXT.md` (daté
2026-08-05) n'a pas encore été mis à jour pour refléter cette amorce.

## Forces en présence

- ADR 0004 (unités calendaires W1/MO1) dérive déjà de D1 sans dépendre du calendrier de marché
  — cette ADR ne remet pas en cause ADR 0004.
- Un calendrier de marché correct doit gérer sessions, jours fériés, fermetures anticipées, DST
  — complexité réelle non triviale, à ne pas sous-estimer.
- Le besoin de fiabilité scientifique (Phase 3, out-of-sample/walk-forward) dépend d'un
  resampling qui respecte les vrais jours de bourse, pas un calendrier UTC naïf.

## Options évaluées

1. **Ne jamais intégrer le calendrier au resampling** — rejeté : laisse une source d'erreur
   silencieuse (bougies calculées sur des jours fériés/hors session) qui fausserait toute
   validation scientifique ultérieure.
2. **Intégrer immédiatement, sans base de calendriers multi-marchés robuste** — rejeté : risque
   de résultats incorrects si le calendrier EODHD est incomplet ou mal testé pour l'instrument
   ciblé.
3. **Intégrer progressivement, calendrier optionnel puis obligatoire une fois validé sur
   NASDAQ/US100, en préservant la compatibilité du resampling UTC existant en repli** (retenu).

## Décision

`market_data.resample` gagne un paramètre de calendrier optionnel, initialement `None` (repli
sur le comportement UTC actuel, non cassant). Une fois validé sur NASDAQ/US100 (le seul marché
actuellement couvert), le calendrier devient recommandé par défaut pour tout nouveau
rééchantillonnage, avec détection explicite des trous (`detect_missing_trading_days`, déjà
existant) branchée sur un vrai chemin de production (contrôle qualité du Data Center). `ADR 0003`
reste valide pour tout usage sans calendrier fourni ; cette ADR l'étend, ne le remplace pas.

## Conséquences positives

- Élimine une source de biais silencieux avant que le moteur de validation scientifique
  (Phase 3) ne s'appuie dessus.
- Réutilise du code déjà écrit et testé (`eodhd/calendar.py`, `quality.detect_missing_trading_days`)
  au lieu d'en écrire un nouveau.

## Conséquences négatives

- Ajoute un paramètre et un chemin de code supplémentaire à `resample.py`, à tester avec et sans
  calendrier pour ne pas régresser le comportement existant (ADR 0003/0004).

## Risques

Un calendrier EODHD incomplet ou erroné pour un marché donné produirait des trous mal détectés —
mitigé en gardant le repli UTC disponible et en validant d'abord sur NASDAQ/US100 uniquement.

## Plan de migration

1. Ticket Phase 2 : brancher `detect_missing_trading_days` sur un vrai contrôle qualité du Data
   Center (actuellement zéro appelant en production).
2. Ticket Phase 2 : ajouter le paramètre calendrier optionnel à `resample.py`, tests de
   non-régression sur le comportement UTC existant.
3. Mise à jour de `CONTEXT.md` (terme "Calendrier de marché" passe de "À confirmer" à
   "Confirmé") une fois branché.

## Critères de réévaluation

Si le projet couvre plusieurs marchés avec des calendriers hétérogènes, réévaluer la robustesse
du calendrier EODHD pour chacun avant de le rendre obligatoire par défaut sur ces marchés.
