# Addendum 23.30 de l'ADR 0025 — journal de décision (NON NORMATIF)

**Statut : INTÉGRÉ à l'ADR 0025 (§23.30) le 2026-10-17. Ce fichier n'est pas une autorité normative.**

Le texte d'autorité est `docs/adr/0025-gate-v-validation-policy-v1.md` : section 23.30 et notes de renvoi de 23.3, 23.10, 23.11,
23.27.2 et 23.27.3. En cas de divergence, l'ADR prévaut. Ce fichier ne répète aucune règle ; il conserve la trace des décisions de l'utilisateur,
des options écartées et des revues. Il remplace le document de proposition `0025-addendum-23.30-PROPOSED.md` (versions v1 à v4), qui ne
fait plus foi et n'existe plus.

## 1. Chronologie

| Date | Étape |
|---|---|
| 2026-10-16 | Revue de B3 : trois points de réconciliation contractuelle (`AI_HANDOFF.md` §51.1). |
| 2026-10-16 | Proposition v1 puis v2, relues (axes Standards et Spec). |
| 2026-10-16 | Décisions de l'utilisateur sur Q-6 et Q-7 (section 2). |
| 2026-10-16 | Versions v3 et v4, relues : contradiction normative nouvelle avec 23.10, nommée Q-8. |
| 2026-10-17 | Décision de l'utilisateur sur Q-8 : option (a). Intégration à l'ADR, B3 v2 clos (`AI_HANDOFF.md` §51.4). |

Numérotation : la question du rattachement des Claims, nommée « Q-5 » par erreur au §51.1 du handoff, est **Q-7**. Q-5 reste la règle
`REAL` « tous les compteurs `OBSERVED` » (23.29.5).

## 2. Décisions de l'utilisateur (citées)

Q-6 (2026-10-16) :
- « Retenir l'asymétrie des preuves. »
- « Un manifeste historique non lié au run ne constitue pas une preuve d'exclusion. »
- « Une preuve positive doit être attribuable à la source auditée et respecter les contrôles applicables. Elle ne neutralise aucune
  anomalie. »
- « Une exclusion exige une preuve liée au run couvrant toutes les données accessibles au calcul, durée des barres comprise. »
- « Ne pas assimiler automatiquement un DataReceipt à cette garantie : vérifier les propriétés effectivement prévues par son contrat. »
- « Sans preuve suffisante, conserver la non-résolution ; aucun faux FRESH. »
- « Distinguer explicitement exposition démontrée et absence d'exposition non démontrée. »

Q-7 (2026-10-16) :
- « Identité = split_plan_id + empreinte recalculée selon le contrat existant. »
- « Exiger le contenu vérifiable du plan désigné, sans imposer un nouveau snapshot physique si le contenu audité suffit déjà. »
- « Ne pas imposer globalement identifiant = nom de répertoire. »
- « Ne pas exiger la concordance de tous les plans partageant seulement un identifiant. »
- « Toute revendication d'empreinte incompatible avec le contenu recalculé reste une incohérence explicite. »

Q-8 (2026-10-17) :
- « J'approuve Q-8 option (a). L'option (b) reste une évolution future distincte ; aucune modification d'E3-A n'est autorisée dans cette
  tranche. »
- Réconciliation de 23.10 demandée : « l'absence de rapport avec W doit être démontrée selon les règles de preuve applicables. Une
  simple absence de recouvrement de la fenêtre d'exécution ne suffit pas. »
- Règle opérationnelle demandée : stabilisation de l'inventaire pendant une campagne, sans contournement « par déplacement,
  suppression, omission de sources pertinentes ou réduction artificielle des racines auditées » ; « suspendre les écritures ne résout pas
  les incertitudes déjà présentes ».

Vocabulaire : l'ADR dit « exposition établie » (23.28, R1). L'ADR emploie « établie » là où la décision de l'utilisateur dit
« démontrée », pour ne pas créer de synonyme.

## 3. Options écartées

- Contrôle du `dataset_snapshot_id` du plan désigné par un Claim (Q-7) ; identifiant égal au nom de répertoire ; variante stricte de
  concordance des copies pour le Claim.
- Manifeste de job comme preuve d'exclusion : rien ne le lie au run qui l'a produit (écrit en fin de job, sans identifiant de job, chemin
  ni hash croisé).
- Q-8 option (b), en plus de (a) : spécifier plus tard une preuve d'exclusion liée au run pour les **nouveaux** jobs. Évolution future
  distincte, non engagée.
- Q-8 option (c) : changer la définition de l'ensemble pertinent ou de `static_sources_digest`. Elle modifierait E3-A publié et ne
  rendrait pas `FRESH` atteignable.

## 4. Revues

| Version | Revue | Constats retenus |
|---|---|---|
| v2 | Standards + Spec | Manifeste non lié au run (chemin vers un faux `FRESH`) ; durée de barre ignorée ; fait inexact sur `git_commit` ; cas de test manquants ; statut de glossaire ; hiérarchie [R]/[N] ; collision du numéro Q-5. |
| v3 | Standards + Spec | Renvoi vers `DataReceipt` : son contenu est défini en 23.5 ; contradiction normative avec 23.10 (Q-8) ; attribution du manifeste ; vocabulaire « établie » ; table de hiérarchie limitée aux clauses de l'ADR. |
| B3 v2 | Standards + Spec | Nullité mixte du manifeste ; `content_hash` mal formé ; bornes civiles inversées neutralisées ; lecteur relatif ; retours mixtes des interprètes ; `ExposureEvidence` non validé. |
| Intégration | Standards + Spec | Voir `AI_HANDOFF.md` §51.4. |

## 5. Glossaire

Quatre termes ont été ajoutés à `CONTEXT.md`, au statut « À confirmer » : fenêtre d'exécution, fenêtre accessible au calcul, exposition
à W, identité d'un plan de split.
