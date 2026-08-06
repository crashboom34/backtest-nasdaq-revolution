# Décomposition progressive de app.py (pages / components / services)

**Statut** : Proposed (Proposé)
**Date** : 2026-08-06

## Contexte

Audit du 2026-08-06 (détail complet dans [`CURRENT_STATE.md` §2](../architecture/CURRENT_STATE.md)) :
`app.py` fait **6 416 lignes**, **126 fonctions top-level**, 7 onglets principaux dont un
(Optimisation) à 10 sous-onglets — un God-object au sens de la dette technique, mélangeant rendu,
calcul, orchestration et décision métier dans un seul fichier.

## Forces en présence

- Aucune refonte visuelle n'est demandée à ce stade (voir `docs/architecture/UI_UX_ARCHITECTURE.md`)
  — cette ADR ne concerne que la structure du code, pas le design.
- Le risque de régression d'un big-bang sur un fichier de cette taille est élevé.
- `ui_data_center.py` existe déjà comme précédent réussi de module séparé, branché proprement
  dans `app.py` par un simple appel de fonction — modèle à répliquer.

## Options évaluées

1. **Ne rien faire** — rejeté : la dette continue de croître à chaque nouvelle fonctionnalité UI
   et bloque une refonte UI/UX sereine (Phase 4).
2. **Réécriture complète en un big-bang** — rejeté : risque de régression majeur sur une
   application dont les tests couvrent surtout le moteur/market_data, peu l'UI elle-même.
3. **Décomposition progressive par onglet, sans big-bang** (retenu) : chaque onglet migre vers
   `pages/`/`components/`/`services/` un par un, en gardant `app.py` fonctionnel à chaque étape.

## Décision

Adopter une structure cible `pages/`, `components/`, `services/` (voir
`docs/architecture/UI_UX_ARCHITECTURE.md` pour le détail), et migrer `app.py` **un onglet à la
fois**, en commençant par les onglets les plus autonomes (Data Center déjà fait implicitement,
Maintenance, Historique manuel) avant les plus couplés (Optimisation, ses 10 sous-onglets).
`app.py` reste l'unique point d'assemblage (`st.tabs` + appels aux modules `pages/`) jusqu'à
disparition complète de la logique métier en son sein.

## Conséquences positives

- Chaque migration est un changement testable et réversible indépendamment.
- Prépare la refonte UI/UX (Phase 4) sans la bloquer ni l'anticiper.

## Conséquences négatives

- Pendant la transition, deux styles cohabitent dans `app.py` (ancien inline, nouveau modulaire)
  — dette temporaire acceptée consciemment.

## Risques

Migration abandonnée à mi-chemin, laissant une incohérence permanente — mitigé en traitant
chaque onglet migré comme un ticket fermé et testé, jamais un chantier ouvert indéfiniment.

## Plan de migration

1. Extraire un onglet à la fois vers `services/` (logique) puis `pages/` (rendu Streamlit).
2. Garder les mêmes clés `st.session_state` pendant la migration pour ne rien casser.
3. Supprimer le code correspondant de `app.py` seulement après validation Playwright de l'onglet
   migré (voir `TEST_AND_VALIDATION_ARCHITECTURE.md`).

## Critères de réévaluation

Si la migration progressive stagne après plusieurs mois sans avancer, réévaluer un big-bang
ciblé sur le seul onglet Optimisation (le plus complexe), avec une couverture de tests Playwright
renforcée au préalable.
