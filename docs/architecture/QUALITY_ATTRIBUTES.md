# Attributs de qualité cibles

> Voir `docs/INDEX.md` pour la navigation. Ces attributs guident tous les choix documentés dans
> `TARGET_ARCHITECTURE.md`, `DEPLOYMENT_ARCHITECTURE.md`, `COMPUTE_AND_JOBS.md` et
> `DATA_ARCHITECTURE.md`.

| Attribut | Aujourd'hui (constaté) | Cible | Mesure |
|---|---|---|---|
| **Indépendance vis-à-vis du poste local** | Backtest simple bloque le thread Streamlit local ; optimisation limitée à la puissance du poste | Le calcul s'exécute sur un serveur externe, l'interface reste réactive | Temps de réponse UI pendant un job actif |
| **Exécution en arrière-plan** | Un job survit à la fermeture du navigateur (déjà vrai) ; survie à la fermeture du serveur non prouvée | Un job survit à un redémarrage du serveur | Test de redémarrage forcé pendant un job actif |
| **Parallélisme** | 1 job actif à la fois, N workers internes sur une seule machine | Plusieurs jobs/workers, potentiellement multi-machines | Débit (combinaisons/seconde) à N workers |
| **Reprise après interruption** | Mécanisme moteur présent mais jamais déclenché | Reprise automatique ou semi-automatique après crash | Job interrompu puis relancé produit un résultat identique |
| **Reproductibilité** | Config sauvegardée, provenance des données vide en pratique | Manifeste avec hash réel systématique | 100 % des manifestes ont un `content_hash` non nul |
| **Observabilité** | Logs texte (`logs.txt`) par job, pas de métriques système centralisées | Logs structurés, métriques CPU/RAM/disque, alertes | Temps de détection d'un job bloqué |
| **Sécurité** | IG démo/lecture seule déjà respecté, pas de secret dans Git (déjà vrai) | Idem + secrets serveur en variables d'environnement/coffre, HTTPS, sauvegardes chiffrées | Revue de sécurité sans finding critique |
| **Évolutivité multi-actifs** | Mono-actif dans le moteur, multi-actifs amorcé côté stockage (`data/{ASSET}/{TIMEFRAME}/`) | Portefeuille multi-actifs, conventions par classe d'actif | Nombre de classes d'actifs supportées sans changement de moteur |
| **Fiabilité scientifique** | Split train/test implémenté ; walk-forward et Monte-Carlo absents (déjà notés "V2" dans la spec de mai) | Out-of-sample, walk-forward, Monte-Carlo obligatoires avant "Champion" | % de stratégies Champion ayant passé toutes les validations |
| **Maintenabilité de l'UI** | `app.py` 6 416 lignes, 126 fonctions | Décomposition modulaire `pages/components/services`, aucun fichier > ~800 lignes | Lignes par fichier UI |
| **Coût raisonnable** | Poste personnel, coût marginal nul | Serveur dimensionné par benchmark, pas de sur-dimensionnement a priori | Coût mensuel vs débit mesuré |
| **Simplicité de déploiement** | Aucun artefact d'infrastructure | `docker-compose up` reproductible en un temps borné | Temps de redéploiement complet depuis zéro |

## Compromis assumés

- **Simplicité avant scalabilité maximale** : monolithe modulaire (ADR 0005), pas de
  microservices, tant que le besoin réel reste mono-utilisateur.
- **Compatibilité avant pureté** : le contrat de job directory fichier reste l'artefact de
  référence même après introduction d'une file de travaux et d'une base de données.
- **Décision différée avant choix prématuré** : technologie de file de travaux (ADR 0006) et
  hébergeur (voir `BENCHMARK_PLAN.md`) tranchés seulement après preuve.
