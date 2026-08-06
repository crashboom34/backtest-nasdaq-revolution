# Registre des risques

> Voir `docs/INDEX.md` pour la navigation. Probabilité/Impact : Faible/Moyen/Élevé. Criticité =
> combinaison des deux (indicative, pas un calcul formel).

| Risque | Probabilité | Impact | Criticité | Détection | Prévention | Mitigation | Phase concernée |
|---|---|---|---|---|---|---|---|
| Saturation disque (serveur ou poste local) | Moyen | Élevé | Élevée | Alerte seuil disque (`SECURITY_AND_OPERATIONS.md`) | Volume NVMe dédié, séparé du code | Politique de rétention (`DECISION_BACKLOG.md`), nettoyage Maintenance existant | 1, 2 |
| Surconsommation RAM (gros backtests/optimisations) | Moyen | Moyen | Moyenne | Métriques CPU/RAM | Benchmark avant dimensionnement (`BENCHMARK_PLAN.md`) | Limiter workers concurrents, alerter avant saturation | 1 |
| Dépendance à Streamlit (limite d'échelle UI) | Faible | Moyen | Faible-Moyenne | — | Interface jamais moteur de calcul (ADR 0005) | Frontend séparé réévaluable (`DECISION_BACKLOG.md`) si besoin | 4 |
| Jobs perdus (crash worker/serveur) | Moyen | Élevé | Élevée | Absence de mise à jour `progress.json` au-delà d'un seuil | File de travaux avec reprise (ADR 0006) | `resume_run_id`/`tested.json` déjà existants côté moteur, à brancher | 1 |
| Résultats non reproductibles | Élevé (constaté aujourd'hui : manifestes vides) | Élevé | Élevée | Audit de manifestes (`content_hash` nul) | ADR 0008 (hash réel systématique) | Bloquer la promotion Champion si manifeste incomplet | 2, 3 |
| Corruption des Parquet | Faible | Élevé | Moyenne | Vérification périodique d'intégrité (à spécifier) | Écriture atomique, hash de contenu | Restauration depuis sauvegarde | 2 |
| Données fournisseurs incomplètes (EODHD/IG) | Moyen | Moyen | Moyenne | Contrôle qualité (`quality.py`) | Contrôle qualité étendu (calendrier, DST) | Signaler explicitement, ne pas masquer | 2 |
| Quotas EODHD dépassés | Moyen | Moyen | Moyenne | Suivi cumulatif (à implémenter, absent aujourd'hui) | Suivi de quota persistant côté client | Alerte avant dépassement | 2 |
| Erreurs DST (changement d'heure) | Moyen | Moyen | Moyenne | Non couvert aujourd'hui (constaté par audit) | Spécification explicite lors du branchement calendrier (ADR 0013) | Tests dédiés sur les dates de changement d'heure | 2 |
| Biais de backtest (look-ahead, survivorship, data snooping) | Moyen | Élevé | Élevée | Audit ciblé du moteur (non fait dans cette mission) | Moteur de validation (Phase 3) | Étiquette "Champion provisoire" tant que non validé | 3 |
| Fuite de secrets | Faible (déjà bien géré aujourd'hui) | Élevé | Moyenne | Scan CI (à implémenter) | Règles déjà en vigueur (`.gitignore`, env only) | Rotation immédiate en cas de fuite constatée | Toutes |
| Dépendance Windows résiduelle | Faible (portabilité meilleure que redouté, constaté) | Faible | Faible | `requirements-server.txt` déjà sans MT5 | Garder `metatrader5` hors du fichier serveur | Aucune action urgente | 1 |
| Coûts serveur imprévus | Moyen (marché en hausse constatée 2026-2028) | Moyen | Moyenne | Suivi mensuel de la facture | Benchmark avant engagement, éviter les engagements longs sans preuve | Réévaluer le profil si le débit/coût se dégrade | 1 |
| Dette technique de `app.py` | Élevé (constaté : 6 416 lignes) | Moyen | Moyenne-Élevée | Taille de fichier, complexité | Décomposition progressive (ADR 0010) | Un onglet à la fois, jamais de big-bang | 4 |
| Complexité prématurée (sur-ingénierie) | Moyen | Moyen | Moyenne | Revue d'ADR (statut Proposed non justifié par preuve) | Décisions différées tant que non prouvées (ADR 0006) | Réévaluer si le besoin réel reste mono-machine | 0, 1 |
| Fournisseur indisponible (EODHD/IG en panne) | Faible | Moyen | Faible-Moyenne | Erreurs de connexion déjà gérées (`error_code`) | Retry/backoff déjà partiellement en place (EODHD 429) | Dégradation gracieuse, pas de blocage total de l'app | 2 |
| Perte de sauvegarde | Faible | Élevé | Moyenne | Test de restauration régulier | Sauvegardes externes au serveur | Restauration testée dès la Phase 1 | 1 |
| Changement d'API IG/EODHD | Moyen (déjà vécu une fois — migration v2→v3 IG) | Moyen | Moyenne | Tests de connexion réguliers | Tests d'intégration hors ligne + scripts manuels existants | Corriger rapidement, pattern déjà rodé sur ce dépôt | 2 |
| Données options insuffisantes | Élevé | Moyen | Moyenne | — | Distinction explicite des 4 catégories (ADR 0011) | Ne jamais présenter du théorique comme réel | 7 |
| Stratégies sur-optimisées | Moyen | Élevé | Élevée | Pénalités déjà en place (scoring) | Walk-forward/Monte-Carlo (Phase 3) | Étiquette Champion provisoire tant que non validé | 3 |
