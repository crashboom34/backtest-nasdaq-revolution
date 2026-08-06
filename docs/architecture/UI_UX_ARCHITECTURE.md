# Architecture UI/UX cible

> Capacité utilisée pour ce document : **UI/UX Pro Max** (skill personnelle, réellement chargée
> via `~/.claude/CLAUDE.md`). Aucune refonte de `app.py` n'est effectuée ici — architecture et
> planification uniquement (voir ADR 0010 pour la stratégie de décomposition du code).

## 1. Architecture de l'information cible

Structure de code cible (préparation, migration progressive — ADR 0010) :

```text
pages/        # rendu Streamlit par espace fonctionnel, fin — délègue à services/
components/   # widgets réutilisables (cartes, tableaux, badges, formulaires)
services/     # logique applicative (appels moteur, jobs, market_data), sans st.*
market_data/  # inchangé — Data Center, EODHD, IG
backtest/     # (regroupement futur de engine.py/scoring.py si pertinent, non décidé)
optimization/ # (regroupement futur de optimizer.py/optimizer_process.py, non décidé)
reporting/    # champion_*.py, report_generator
settings/     # inchangé — configuration
```

## 2. Navigation cible — dix espaces fonctionnels

| Espace | Objectif | Utilisateurs | Infos principales | Actions | Composants | Erreurs possibles | Métriques | Dépendances backend | Tests Playwright futurs |
|---|---|---|---|---|---|---|---|---|---|
| **Accueil** | Vue de santé du système en un coup d'œil | Utilisateur unique aujourd'hui | Santé serveur, derniers backtests, stratégies prometteuses, espace disque, jobs actifs | Naviguer vers un job/résultat | Cartes de statut, liste de jobs actifs | Aucune donnée disponible (état vide) | Temps de chargement de la page | `job_store`, `optimization_store`, futur `services/health` | Vérifier que les cartes reflètent l'état disque/jobs réel |
| **Data Center** | Gérer fournisseurs/instruments/qualité | Utilisateur unique | Catalogue unifié, statut fournisseurs, qualité, synchro, dividendes/splits | Tester connexion, déclencher synchro (futur), consulter qualité | Table de catalogue, badges de statut, boutons de test | Échec connexion fournisseur, quota dépassé | Fraîcheur des données, score qualité | `market_data/*`, `ui_data_center.py` (déjà existant) | Parcours "tester connexion EODHD/IG" déjà couvert manuellement — formaliser en Playwright |
| **Laboratoire de stratégies** | Choisir/configurer une stratégie | Utilisateur unique | Liste des stratégies découvertes, paramètres, schéma | Sélectionner, éditer les paramètres | Sélecteur de stratégie, formulaire généré depuis `PARAM_SCHEMA` | Stratégie invalide (contrat manquant) | — | `strategies/*.py`, découverte dynamique existante | Sélection stratégie → paramètres corrects affichés |
| **Backtest** | Lancer un backtest unique | Utilisateur unique | Configuration simple, mode rapide/approfondi, estimation temps | Lancer, arrêter | Formulaire de config, estimation | Données manquantes, plage de dates invalide | Temps d'exécution réel vs estimé | `engine.py` (inchangé) | Lancement backtest simple, affichage résultat |
| **Optimisation** | Lancer/suivre une campagne | Utilisateur unique | Combinaisons, workers, progression | Lancer, arrêter, reprendre (futur) | Barre de progression, config workers | Job déjà actif (verrou), échec worker | Débit (combinaisons/s) | `job_launcher.py`, future file de travaux | Lancement, progression, arrêt propre |
| **Validation** | Fiabilité scientifique | Utilisateur unique | Out-of-sample, walk-forward, Monte-Carlo, robustesse | Lancer une campagne de validation | Graphiques de robustesse | Échantillon trop petit | Ratio in-sample/out-of-sample | Nouveau moteur de validation (Phase 3, non existant) | Résultats de validation cohérents avec un cas connu |
| **Résultats** | Analyser un backtest/run | Utilisateur unique | Courbe de capital, drawdown, trades, distributions | Filtrer, exporter | Graphiques Plotly, table de trades | Résultat corrompu/absent | — | `job_store`, `report_generator` | Rendu correct pour un job de référence |
| **Champions** | Comparer/valider les meilleures stratégies | Utilisateur unique | Classement, stabilité, comparaison | Promouvoir/rejeter un Champion | Table de classement, badges de validation | Critères Champion non remplis | Nombre de Champions validés | `champion_*.py` (déjà existants) | Promotion respecte les règles de `TEST_AND_VALIDATION_ARCHITECTURE.md` |
| **Historique** | Retrouver/reproduire un ancien test | Utilisateur unique | Recherche, filtres, archives | Rechercher, ré-ouvrir, reproduire | Barre de recherche, filtres | Job archivé introuvable | — | `history_store.py`, `job_comparison.py` | Recherche retrouve un job connu |
| **Administration** | Superviser l'infrastructure | Utilisateur unique (futur : admin séparé, Phase 8) | État serveur, stockage, fournisseurs, secrets (statut seulement), logs | Voir logs, relancer un service (futur) | Tableaux de bord système | Service indisponible | CPU/RAM/disque | Observabilité (voir `SECURITY_AND_OPERATIONS.md`) | Affichage correct du statut système |

## 3. Design system (à préparer, non implémenté ici)

- **Palette** : conserver le thème sombre déjà défini dans `.streamlit/config.toml`
  (`primaryColor #4477ff`, fond `#0a0a14`) comme point de départ, à documenter en tokens.
- **Composants de base à formaliser** : carte de statut, badge (Confirmé/À confirmer/Erreur),
  tableau de résultats, formulaire de paramètres généré depuis un schéma, barre de progression
  de job.
- **États systématiques par composant** : vide, chargement, erreur, succès — aujourd'hui gérés
  au cas par cas dans `app.py`, à standardiser lors de la décomposition (ADR 0010).
- **Accessibilité** : contrastes WCAG 2.1 AA à vérifier sur le thème sombre existant ; labels
  explicites sur tous les formulaires de paramètres générés dynamiquement.
- **Responsive** : Streamlit gère nativement une partie du responsive ; les tableaux larges
  (résultats, catalogue) devront rester scrollables horizontalement sans casser la mise en page.

## 4. Stratégie de migration progressive (résumé — détail dans ADR 0010)

1. Ne jamais faire de big-bang sur `app.py`.
2. Migrer un onglet à la fois vers `pages/`/`components/`/`services/`, en commençant par les plus
   autonomes (Maintenance, Historique manuel), avant les plus couplés (Optimisation).
3. Chaque migration se termine par une validation Playwright de l'onglet concerné avant de
   retirer le code équivalent de `app.py`.
4. La refonte visuelle complète (nouveau design system appliqué partout) n'intervient qu'après
   stabilisation des services (Phase 4, après le serveur de staging — voir `MASTER_ROADMAP.md`).

## 5. Performance Streamlit

Points à surveiller lors de la décomposition (pas de changement de code dans cette mission) :
recalculs inutiles sur rerun, taille des DataFrames chargés en mémoire de session, mise en cache
(`st.cache_data`) pour les lectures de catalogue/résultats répétées.
