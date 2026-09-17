# Direction produit UX/UI — AlphaForge V2

> **Nature de ce document : direction produit/UX acceptée, PAS une refonte.** Aucun composant
> `app.py`/Streamlit n'est modifié par ce document. Il complète, sans le dupliquer,
> `docs/architecture/UI_UX_ARCHITECTURE.md` (architecture de l'information, navigation technique,
> migration progressive, ADR 0010) : **ce document-ci porte la philosophie produit/pédagogique**
> (pourquoi et comment parler à l'utilisateur), l'autre porte **l'architecture de code cible**
> (où vit quoi). Lire les deux, jamais l'un à la place de l'autre.
>
> Produit lors de la mission de synchronisation produit/UX/roadmap du 2026-09-16 (documentaire
> uniquement). Aucune fonctionnalité UX ci-dessous n'est implémentée — statuts explicites au §0 de
> `docs/product/PRODUCT_VISION_V2.md`, repris ici section par section.

## 0. Statut global de ce document

**`ACCEPTED PRODUCT DIRECTION / IMPLEMENTATION DEFERRED`** pour l'ensemble, sauf mention contraire
explicite section par section (quelques principes portent `ACCEPTED` seul — ce sont des règles de
conception à respecter **dès qu'une future phase UX/UI commence**, pas des composants à livrer).

## 1. Principe fondamental

**Simple au premier niveau, puissant en profondeur.** La future interface doit être : entièrement
en français côté utilisateur, premium, épurée, moderne, cohérente, très lisible, ergonomique,
accessible aux néophytes, utilisable par des experts. Statut : `ACCEPTED PRODUCT DIRECTION /
IMPLEMENTATION DEFERRED`.

## 2. Mode guidé par défaut

**Statut : `ACCEPTED`.** La vue par défaut explique simplement : ce qui s'est passé, si le
résultat est positif ou problématique, pourquoi, quelle est la prochaine étape. Les paramètres
complexes sont masqués/repliés au premier niveau — jamais supprimés (voir §3).

## 3. Mode expert / détails avancés

**Statut : `ACCEPTED`.** Conserver l'accès complet : métriques, paramètres, versions, seeds,
broker model, coûts, données, logs, détails scientifiques. **Ne jamais supprimer la puissance du
produit au nom de la simplicité** — le mode guidé (§2) et le mode expert coexistent toujours,
jamais l'un au prix de l'autre.

## 4. Langue française

Textes utilisateurs en français. Standards pouvant rester en anglais : *Backtest*, *Walk-Forward*,
*Monte-Carlo*, *Sharpe*, *OOS* — **toujours accompagnés d'une explication pédagogique** (voir
§6-§7 pour le pattern exact). Statut : `ACCEPTED`.

## 5. Interprétation des métriques (pattern réutilisable)

**Statut : `ACCEPTED`.** Chaque métrique importante suit ce gabarit :

```text
### Perte maximale
-12,4 %
« Au pire moment du backtest, le portefeuille a perdu 12,4 % depuis son précédent sommet. »
[Voir les détails avancés]
```

Chiffre brut → phrase d'explication en langage naturel → accès optionnel au détail technique.
S'applique à toute métrique jugée importante pour la compréhension (pas seulement le drawdown).

## 6. Explication « Pourquoi ? »

**Statut : `ACCEPTED`.** Pattern réutilisable pour tout résultat qualitatif :

```text
🟠 Stabilité moyenne
[Pourquoi ?]
« Les performances diminuent fortement lorsque certains paramètres sont légèrement modifiés. »
```

## 7. Assistant de lecture

**Statut : `ACCEPTED / DEFERRED`** (voir `docs/product/PRODUCT_VISION_V2.md` §24). Synthèse
pédagogique fondée sur des règles/métriques **réellement disponibles** :

```text
« Les performances historiques sont intéressantes mais la validation Walk-Forward n'a pas encore
été effectuée. La robustesse ne peut donc pas encore être confirmée. »
```

**Règle absolue, jamais négociable** : ne jamais laisser un LLM (ou toute logique non auditée)
inventer un verdict scientifique. Toute phrase produite par cet assistant doit être dérivable d'un
fait déjà présent dans `ValidationEvidence`/`WalkForwardEvidence`/etc. — jamais une estimation
générée sans preuve traçable (même discipline que Décision 13 de l'ADR 0021 : `execution_status`
distinct de `scientific_verdict`, aucune valeur inventée pour combler une absence de preuve).

## 8. Navigation produit cible — tension à réconcilier (non résolue ici)

La mission source propose 12 espaces : *Accueil, Créer une stratégie, Recherche & optimisation,
Backtests, Validation, Stratégies, Champions, Portefeuilles, Données, Calculs, Suivi, Paramètres.*

`docs/architecture/UI_UX_ARCHITECTURE.md` §2 documente déjà, depuis une mission antérieure
(2026-08-06), **10 espaces** : *Accueil, Data Center, Laboratoire de stratégies, Backtest,
Optimisation, Validation, Résultats, Champions, Historique, Administration.*

**Ces deux structures ne coïncident pas terme à terme** (ex. « Créer une stratégie » vs
« Laboratoire de stratégies » ; « Calculs »/« Suivi » sans correspondance directe évidente côté
architecture existante ; « Administration » absent de la liste à 12). **Ce document ne tranche
pas** cette divergence — signalé explicitement comme risque (voir rapport de mission et
`docs/product/PRODUCT_VISION_V2.md` §"Risques"). Quand la phase UX/UI démarrera réellement
(`ui-ux-pro-max` + `Playwright`, §11 ci-dessous), une réconciliation explicite des deux listes
devra être un livrable à part entière, pas une fusion silencieuse.

Règle commune aux deux structures, non ambiguë : **ne jamais présenter une page comme
opérationnelle lorsqu'elle ne l'est pas** — adapter la navigation affichée aux fonctions
réellement disponibles, jamais l'inverse.

## 9. Performance ≠ Robustesse (principe UX obligatoire)

Ne jamais confondre **performance historique** et **robustesse scientifique**. Une stratégie à
+500 % *in-sample* peut toujours avoir une **VALIDATION INCOMPLÈTE** — l'UI doit rendre cette
distinction évidente, systématiquement, jamais seulement dans un écran secondaire. Statut :
`ACCEPTED` (principe non négociable, indépendant du calendrier d'implémentation).

## 10. Niveau de preuve (Evidence Ladder)

**Statut : `ACCEPTED / DEFERRED`.** Système explicable fondé sur les validations **réellement
passées**, jamais un score opaque arbitraire :

```text
Backtest historique ✅
OOS               ✅
Walk-Forward      ⏳
Monte-Carlo       ⏳
Stabilité         ⏳
Final Holdout     🔒
```

Chaque ligne correspond à un `validation_type` réel du registre `_VALIDATION_TYPES`
(`validation_run.py`) ou à un état d'accès `FINAL_HOLDOUT` réel (`HoldoutAccessEvent`) — jamais
une case cochée sans preuve `ValidationRun`/`ValidationEvidence` correspondante derrière.

## 11. Design system (direction visuelle)

**Statut : `ACCEPTED PRODUCT DIRECTION / IMPLEMENTATION DEFERRED`.** Thème **clair premium en
priorité** (note : différent du thème sombre actuellement documenté comme point de départ dans
`UI_UX_ARCHITECTURE.md` §3 — divergence à trancher explicitement lors de la conception réelle du
design system, pas silencieusement). Fond doux, surfaces blanches, accent bleu pétrole/teal, bleu
secondaire, vert succès, orange vigilance, rouge erreur, zones respirantes, cartes sobres,
bordures fines, typographie moderne, graphiques lisibles. **Explicitement rejeté** : esthétique
crypto/gaming, effets visuels gratuits. Un vrai design system réutilisable reste à créer
ultérieurement — non fait ici.

## 12. Grammaire de statuts visuels

**Statut : `ACCEPTED`.** 🟢 satisfaisant · 🟠 vigilance/incomplet · 🔴 problème/échec · 🔵
information · ⚪ non exécuté · 🔒 protégé. **La couleur ne doit jamais être le seul vecteur
d'information** (accessibilité — cohérent avec `UI_UX_ARCHITECTURE.md` §3, contrastes WCAG 2.1
AA déjà notés comme point à vérifier) : toujours accompagner d'un libellé texte ou d'une icône
distincte.

## 13. Outils pour la future phase UX/UI

Lors de la future phase UX/UI réelle (non commencée par cette mission), l'agent devra :

- vérifier la disponibilité réelle de `ui-ux-pro-max` (skill personnelle) et de la bibliothèque
  `playwright` (outil natif du projet, canal `msedge`, voir `CLAUDE.md`) avant de les invoquer —
  jamais supposer, jamais inventer un skill ;
- utiliser les autres skills pertinents disponibles à ce moment (le tableau de routage de
  `CLAUDE.md` peut avoir changé — revérifier) ;
- indiquer explicitement, dans le rapport de cette future mission, lesquels ont été réellement
  invoqués ;
- utiliser `Playwright` pour valider l'application **réellement rendue** : navigation, responsive,
  textes, interactions, erreurs console, captures d'écran, desktop/laptop — jamais une validation
  seulement visuelle/déclarative.

## Vérification de cohérence avec l'existant (effectuée pour cette mission)

- `docs/architecture/UI_UX_ARCHITECTURE.md` : lu intégralement, **non modifié** — reste la source
  pour l'architecture de code/navigation technique. Une divergence de navigation est signalée
  (§8), pas résolue.
- Palette : le thème sombre déjà en place (`.streamlit/config.toml`, `primaryColor #4477ff`, fond
  `#0a0a14`) **n'est pas remplacé** par la direction « clair premium » de ce document — les deux
  sont notées comme une tension à trancher explicitement lors de la conception réelle, jamais un
  changement silencieux de thème par cette mission documentaire.
- Aucun fichier `app.py`/Streamlit/CSS touché.
