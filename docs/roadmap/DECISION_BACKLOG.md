# Backlog de décisions ouvertes

> Voir `docs/INDEX.md` pour la navigation. Aucune de ces décisions n'est prise dans cette mission
> — chacune nécessite une preuve (benchmark, prototype) ou une clarification avant tranchage.

## Décision tranchée (retirée du backlog)

**Fournisseur cloud** : Oracle Cloud Infrastructure Pay As You Go, cible principale — voir
[ADR 0015](../adr/0015-oracle-cloud-infrastructure-payg.md) (statut Accepted/Accepté). Hetzner
reste une alternative conditionnelle si l'usage devient intensif et permanent. OVHcloud/Scaleway
documentés dans `BENCHMARK_PLAN.md` mais ne sont plus la cible principale. Cette décision ne fige
**pas** les détails ci-dessous, toujours ouverts.

| Décision | Informations manquantes | Prototype requis | Benchmark requis | Coût de changement | Phase/date à laquelle décider |
|---|---|---|---|---|---|
| RQ ou Celery (ADR 0006) | Comportement réel sous crash/reprise | Oui — sur un scénario représentatif | Oui | Moyen (migration de l'orchestration) | Avant Phase 1 |
| Région OCI | Latence réelle depuis la localisation de l'utilisateur, disponibilité des formes de calcul par région | Non | Non (test de latence simple) | Faible avant usage, moyen après (données région-locked) | Phase 0 |
| Forme de VM flexible ou fixe (OCI) | Aucune — flexible recommandé par défaut (ADR 0015), à confirmer par benchmark | Non | Oui | Faible (reconfigurable) | Phase 0 |
| 8 ou 16 vCPU (profil recommandé OCI) | Débit réel mesuré par le benchmark Phase 0 | Non | Oui (`BENCHMARK_PLAN.md`) | Faible (formes flexibles) | Phase 0 |
| Quantité de RAM (profil recommandé OCI) | Idem vCPU | Non | Oui | Faible | Phase 0 |
| Block Volume ou Object Storage par type de donnée | Modèle d'accès réel (lecture séquentielle vs aléatoire) par type de donnée | Non | Non (étude technique) | Moyen (migration de données) | Phase 0-1 |
| Serveur unique ou plusieurs nœuds | Débit réel mesuré vs besoin | Non | Oui | Élevé (refonte déploiement) | Après Phase 1, si besoin réel |
| PostgreSQL auto-hébergé (sur la VM) ou managé (OCI Autonomous/DB System) | Coût comparatif réel au moment de la décision | Non | Non (comparaison de prix) | Moyen | Avant production (Phase 8), auto-hébergé par défaut en staging |
| Redis auto-hébergé (sur la VM) ou séparé | Besoin réel de séparation avant qu'un besoin de charge le justifie | Non | Non | Faible (staging), moyen (prod) | Phase 1, auto-hébergé par défaut en staging |
| Stockage local, objet, ou hybride | Volume réel de données à moyen terme | Non | Non | Élevé (migration de données) | Phase 2, réévalué en Phase 5 (multi-actifs) |
| Terraform, OCI CLI ou procédure manuelle | Fréquence réelle de recréation d'instances | Non | Non | Faible (staging), moyen (si scripté tardivement) | Phase 0-1, procédure manuelle documentée d'abord |
| Instance permanente légère + worker temporaire puissant, ou tout-en-un | Coût comparé mesuré par le benchmark et le journal d'usage | Non | Oui (dérivé du benchmark) | Moyen (refonte du cycle de démarrage) | Phase 1, après premier usage réel mesuré |
| Mécanisme exact de démarrage/arrêt des workers OCI (API OCI, script planifié, autre) | Fiabilité comparée des options | Oui (prototype minimal) | Non | Faible | Phase 0-1 |
| Outil de monitoring (natif OCI, Prometheus/Grafana, solution plus simple) | Besoin réel de tableaux de bord avancés | Non | Non | Faible-Moyen | Phase 1 (minimal) à Phase 4 (avancé) |
| Stratégie de migration vers Hetzner si nécessaire | Dépend du critère de réévaluation de l'ADR 0015 (usage intensif/permanent constaté) | Non | Oui (comparaison de coût mesuré) | Élevé (changement de fournisseur de calcul) | Réévalué en continu, jamais avant un usage réel mesuré |
| Caddy ou Nginx | Préférence opérationnelle, pas de preuve technique bloquante | Non | Non | Faible | Phase 1 |
| Prometheus/Grafana ou solution plus simple | Besoin réel de tableaux de bord avancés | Non | Non | Faible-Moyen | Phase 1 (minimal) à Phase 4 (avancé) |
| Interface Streamlit à long terme ou frontend séparé | Limites réelles de Streamlit rencontrées en usage | Non | Non | Élevé (réécriture UI) | Réévalué en Phase 4 si limites constatées |
| DSL de stratégie (ADR 0014) | Couverture réelle des cas par un DSL simple | Oui | Non | Moyen-Élevé | Phase 6 |
| Support crypto | Besoin utilisateur non confirmé | Non | Non | Moyen (nouvelle classe d'actif) | Phase 5 |
| Support futures | Besoin utilisateur non confirmé | Non | Non | Moyen | Phase 5 |
| Options historiques réelles ou théoriques | Disponibilité et coût des sources de données réelles | Non | Non (étude de sources) | Élevé | Phase 7 |
| Multi-utilisateur | Besoin de partage/collaboration non confirmé | Non | Non | Élevé (authentification, rôles) | Phase 8, si commercialisation engagée |
| Commercialisation | Décision produit, hors périmètre architectural | Non | Non | Élevé | Explicitement non engagée à ce stade |
| Politique de rétention exacte (logs, brut EODHD, job directories anciens) | Coût de stockage réel vs valeur de rétention longue | Non | Non | Faible | Phase 1-2 |
| RPO/RTO cibles précis | Tolérance réelle de l'utilisateur à une perte de données | Non | Non | Faible à définir, élevé si mal choisi après coup | Phase 1 |
| Migration du "backtest simple" vers la file de travaux | Besoin réel de non-blocage de l'UI pendant un backtest simple | Non | Non | Moyen | Phase 1, si besoin constaté |

## Comment ce backlog doit être utilisé

Chaque ticket bloqué par une de ces décisions (voir `EPICS_AND_TICKETS.md`) doit référencer
explicitement la ligne correspondante ici — jamais de fausse précision sur un chantier qui
dépend encore d'une décision non prise.
