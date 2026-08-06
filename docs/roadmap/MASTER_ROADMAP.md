# Feuille de route générale (Master Roadmap)

> Voir `docs/INDEX.md` pour la navigation. Détail des tickets : `EPICS_AND_TICKETS.md`.
> Dépendances entre chantiers : `DEPENDENCY_MAP.md`. Risques : `RISK_REGISTER.md`. Décisions
> ouvertes : `DECISION_BACKLOG.md`.

Prochaine action unique recommandée : **Phase 0**, voir fin de ce document.

---

## Phase 0 — Préparation Oracle Cloud et portabilité Linux

- **Objectif** : disposer d'une architecture cible validée, d'ADR formalisées (dont
  [ADR 0015](../adr/0015-oracle-cloud-infrastructure-payg.md) — Oracle Cloud Infrastructure PAYG
  retenu), d'un protocole de benchmark exécuté (local puis OCI), et d'un profil OCI choisi avec
  preuves avant tout déploiement réel de staging.
- **Prérequis** : aucun pour le sous-ensemble documentaire (déjà livré) ; un compte OCI (palier
  Always Free suffisant pour démarrer) pour le sous-ensemble benchmark/préparation technique.
- **Dépendances** : aucune.
- **Livrables** : les documents de `docs/architecture/`, `docs/roadmap/`, les ADR 0005-0015 ;
  puis, pour la partie technique restante : audit Linux exécuté, dépendances Windows
  supprimées/isolées, squelette Docker Compose local fonctionnel, séparation interface/exécution
  amorcée, Redis/PostgreSQL préparés en local, stockage persistant OCI défini, benchmark local
  puis OCI exécuté, comparaison des profils, architecture réseau définie, secrets sécurisés,
  sauvegarde/restauration testées, arrêt automatique défini, contrôle des coûts défini, critères
  Go/No-Go évalués.
- **Sous-chantiers couverts** (voir `docs/roadmap/EPICS_AND_TICKETS.md`, tickets `PH0-OCI-01` à
  `PH0-OCI-10`) :
  1. Audit Linux (portabilité déjà largement confirmée — voir `CURRENT_STATE.md` §3, reste à
     valider en conditions réelles).
  2. Suppression ou isolation des dépendances Windows (`metatrader5`, déjà hors
     `requirements-server.txt`).
  3. Dockerisation locale (squelette `docker-compose.yml`, sans OCI, pour valider la structure).
  4. Séparation interface et exécution (prérequis de l'ADR 0005, amorcée avant tout déploiement).
  5. Préparation de Redis et PostgreSQL (configuration locale, avant décision managé/auto-hébergé).
  6. Préparation du stockage persistant (Block Volume vs Object Storage — voir `DATA_ARCHITECTURE.md`).
  7. Benchmark local reproductible (protocole `BENCHMARK_PLAN.md` §1, exécuté sur le poste actuel
     comme référence).
  8. Benchmark OCI (même protocole, exécuté sur une instance OCI réelle).
  9. Comparaison des profils OCI (Minimal/Recommandé/Intensif temporaire, `BENCHMARK_PLAN.md` §2).
  10. Architecture réseau (région, VCN, exposition — décisions ouvertes, `DECISION_BACKLOG.md`).
  11. Sécurité des secrets (variables d'environnement OCI, jamais dans l'image/le dépôt).
  12. Sauvegarde et restauration (testées réellement, pas seulement écrites).
  13. Arrêt automatique (mécanisme technique indépendant, `SECURITY_AND_OPERATIONS.md` §7).
  14. Contrôle des coûts (estimation, quotas, alertes, confirmation utilisateur, arrêt d'urgence).
  15. Critères Go/No-Go avant le staging (voir critères de sortie ci-dessous).
- **Critères d'entrée** : dépôt à jour, propre (déjà vérifié) ; décision Oracle validée
  (ADR 0015, déjà acté).
- **Critères de sortie (Go/No-Go avant Phase 1)** : documents relus (`/code-review`, déjà fait) ;
  audit Linux validé en conditions réelles sur une instance OCI ; benchmark exécuté localement et
  sur OCI, profil choisi avec preuves ; arrêt automatique et protections de coût opérationnels
  **avant** tout usage réel de workers payants ; sauvegarde/restauration testées au moins une
  fois ; secrets gérés hors dépôt sur l'instance de test.
- **Risques** : sur-ingénierie prématurée si les décisions ADR "Decision pending"/backlog sont
  tranchées sans preuve ; facture OCI imprévue si le benchmark réel démarre avant que les
  protections de coût (§7 `SECURITY_AND_OPERATIONS.md`) existent — **ne pas exécuter PH0-OCI-09
  (benchmark OCI réel) avant PH0-OCI-06/07 (arrêt automatique, protections budgétaires)**.
- **Rollback** : le palier Always Free permet d'expérimenter sans engagement financier ; toute
  ressource OCI payante créée pour le benchmark doit être détruite explicitement après usage.
- **Tests** : revue documentaire (`/code-review`, déjà fait) ; tests d'exécution réelle du
  pipeline existant sur instance OCI (pas de nouveau test logiciel écrit dans cette phase).
- **Effort** : L (documentation, déjà livrée) puis L supplémentaire (benchmark et préparation
  technique restants).
- **Compétences** : architecture logicielle, DevOps/Linux, lecture de code existant, notions
  Oracle Cloud Infrastructure.
- **Skills Claude Code recommandés** : `codebase-design`, `domain-modeling`, `Agent`/`Workflow`
  (audits parallèles), `to-tickets`, `code-review`, `WebSearch`/`WebFetch` (documentation
  officielle Oracle).
- **Hors périmètre explicite** : déploiement réel de staging (Phase 1), toute modification de
  code, toute ressource OCI payante laissée active au-delà du benchmark, tout compte/VM/volume/
  base/réseau créé dans les missions de documentation.

## Phase 1 — Serveur de staging

- **Objectif** : une instance OCI de staging fonctionnelle, avec interface + workers + Redis +
  PostgreSQL + stockage persistant + secrets + HTTPS + sauvegardes + observabilité minimale +
  arrêt automatique opérationnel.
- **Prérequis** : Phase 0 terminée **et critères Go/No-Go validés** (architecture validée, profil
  OCI choisi par benchmark, protections de coût opérationnelles).
- **Dépendances** : ADR 0006 tranchée (RQ vs Celery) avant l'implémentation de la file de
  travaux ; ADR 0009 (Docker Compose) ; ADR 0015 (Oracle Cloud Infrastructure PAYG).
- **Livrables** : `docker-compose.yml`, secrets gérés hors dépôt, premier déploiement staging
  accessible, sauvegarde testée au moins une fois.
- **Critères d'entrée** : profil serveur "recommandé" benchmarké et commandé.
- **Critères de sortie** : un job de test complet (backtest + optimisation réduite) s'exécute sur
  le serveur de bout en bout, survit à un redémarrage simulé, résultat téléchargeable.
- **Risques** : sous-estimation de la complexité Docker/Redis/PostgreSQL pour une première mise
  en place ; voir `RISK_REGISTER.md`.
- **Rollback** : conserver le fonctionnement local (poste actuel) intact en parallèle tant que le
  serveur n'est pas validé — aucune bascule irréversible.
- **Tests** : `test_e2e_subprocess.py`/`test_e2e_parallel.py` adaptés au contexte serveur, plus un
  test de redémarrage forcé.
- **Effort** : XL.
- **Compétences** : DevOps (Docker, Linux, réseau), Python.
- **Skills Claude Code recommandés** : `implement`, `tdd`, `code-review` (une fois le
  déploiement autorisé — hors périmètre de cette mission).
- **Hors périmètre explicite** : production, multi-nœuds (niveau 2), authentification
  multi-utilisateur.

## Phase 2 — Industrialisation du Data Center

- **Objectif** : téléchargements incrémentaux fiables, snapshots complets, calendrier branché,
  corporate actions intégrées, qualité et provenance fiables, quotas suivis.
- **Prérequis** : Phase 1 (stockage serveur disponible) recommandé mais partiellement faisable en
  local (branchement calendrier, correction du manifeste — ADR 0008/0013 — ne dépendent pas du
  serveur).
- **Dépendances** : ADR 0008 (stockage/provenance), ADR 0013 (calendrier).
- **Livrables** : `job_store.write_data_manifest()` corrigé (hash réel), calendrier branché à
  `resample.py`, reprise après interruption du téléchargement EODHD, suivi de quota cumulatif,
  dividendes/splits/titres radiés branchés au catalogue.
- **Critères d'entrée** : ADR 0008/0013 acceptées.
- **Critères de sortie** : 100 % des nouveaux manifestes ont un `content_hash` réel ; un test de
  détection de trous calendaires passe sur un cas connu.
- **Risques** : régression du resampling existant (ADR 0003/0004) si le calendrier est mal
  intégré — mitigé par un paramètre optionnel avec repli UTC.
- **Rollback** : le paramètre calendrier reste optionnel, repli sur le comportement actuel.
- **Tests** : `/tdd` sur chaque branchement (déjà la pratique de ce dépôt).
- **Effort** : L.
- **Compétences** : Python, séries temporelles, données financières.
- **Skills Claude Code recommandés** : `tdd`, `implement`, `code-review`.
- **Hors périmètre explicite** : nouveaux fournisseurs de données au-delà d'EODHD/IG.

## Phase 3 — Fiabilité scientifique

- **Objectif** : out-of-sample, walk-forward, Monte-Carlo, modèle d'exécution réaliste, règles
  Champion formalisées.
- **Prérequis** : Phase 2 (provenance fiable indispensable pour des résultats de validation
  crédibles).
- **Dépendances** : `docs/architecture/TEST_AND_VALIDATION_ARCHITECTURE.md`.
- **Livrables** : moteur de validation (walk-forward, Monte-Carlo), critères Champion formalisés
  et validés avec l'utilisateur (`/domain-modeling`), audit du look-ahead bias.
- **Critères d'entrée** : Phase 2 terminée.
- **Critères de sortie** : une stratégie de référence peut être évaluée de bout en bout
  (walk-forward + Monte-Carlo) et produit un rapport de robustesse consolidé.
- **Risques** : complexité sous-estimée du Monte-Carlo/walk-forward (déjà noté "V2, reporté" dans
  la spec de mai 2026 — signal que ce chantier a déjà été jugé non trivial).
- **Rollback** : les stratégies "Champion provisoire" existantes restent valides sous cette
  étiquette tant que la validation complète n'est pas passée.
- **Tests** : `/tdd`, cas de référence connus (résultats attendus sur un scénario simple avant
  d'appliquer à Perfect Revolution V1).
- **Effort** : XL.
- **Compétences** : statistiques, finance quantitative, Python.
- **Skills Claude Code recommandés** : `domain-modeling` (formaliser "Champion"), `tdd`,
  `implement`, `code-review`.
- **Hors périmètre explicite** : multi-actifs, options.

## Phase 4 — Refonte UI/UX

- **Objectif** : décomposition modulaire de `app.py`, nouveau design system, nouveaux parcours,
  tests Playwright, accessibilité.
- **Prérequis** : services stabilisés (Phase 1-3) — ne pas refondre l'UI avant que ce qu'elle
  affiche soit stable.
- **Dépendances** : ADR 0010 (décomposition progressive).
- **Livrables** : structure `pages/`/`components/`/`services/` en place pour au moins les onglets
  prioritaires, design system documenté, tests Playwright par parcours migré.
- **Critères d'entrée** : Phase 1 validée (le backend ne bouge plus sous les pieds de l'UI).
- **Critères de sortie** : `app.py` réduit significativement, chaque onglet migré validé par un
  test Playwright.
- **Risques** : régression visuelle/fonctionnelle non détectée — mitigé par Playwright avant
  suppression du code équivalent.
- **Rollback** : migration onglet par onglet, jamais de big-bang (ADR 0010) — un onglet peut être
  réverti indépendamment.
- **Tests** : Playwright (canal `msedge`), tests Streamlit existants.
- **Effort** : XL (répartie sur plusieurs sous-chantiers par onglet).
- **Compétences** : UI/UX, Streamlit, Playwright.
- **Skills Claude Code recommandés** : `ui-ux-pro-max`, bibliothèque `playwright`, `implement`,
  `code-review`.
- **Hors périmètre explicite** : changement de framework (rester sur Streamlit sauf décision
  contraire explicite en `DECISION_BACKLOG.md`).

## Phase 5 — Multi-actifs et portefeuille

- **Objectif** : généraliser le moteur au-delà du NASDAQ/US100 mono-actif, portefeuille,
  exposition, corrélation, allocation.
- **Prérequis** : Phase 3 (le moteur de validation doit exister avant de le complexifier avec
  plusieurs actifs).
- **Dépendances** : `docs/architecture/DOMAIN_MODEL.md` §6.
- **Livrables** : modèle d'instrument étendu par classe d'actif, `Portfolio`, calcul d'exposition.
- **Critères d'entrée** : Phase 3 terminée.
- **Critères de sortie** : un backtest multi-actifs simple (2 instruments) produit un résultat
  cohérent avec le modèle de portefeuille.
- **Risques** : le moteur actuel (mono-actif par construction) peut nécessiter des changements
  profonds non anticipés — à confirmer par un audit dédié en amont de cette phase.
- **Rollback** : le mode mono-actif actuel reste le chemin par défaut, multi-actifs additif.
- **Tests** : `/tdd`.
- **Effort** : XL.
- **Compétences** : finance multi-actifs, Python.
- **Skills Claude Code recommandés** : `domain-modeling`, `codebase-design`, `tdd`, `implement`.
- **Hors périmètre explicite** : options (Phase 7, isolée par ADR 0011).

## Phase 6 — Éditeur de stratégies

- **Objectif** : permettre la création de stratégies sans modifier directement du Python (si la
  décision ADR 0014 va dans ce sens).
- **Prérequis** : ADR 0014 tranchée.
- **Dépendances** : contrat `Strategy` existant (`reset/prepare/on_bar`) à respecter comme cible
  de compilation.
- **Livrables** : selon décision — DSL avec sandboxing, ou documentation explicite du choix
  "Python uniquement" si retenu.
- **Critères d'entrée** : ADR 0014 acceptée avec preuves (prototype comparé au contrat existant).
- **Critères de sortie** : une stratégie DSL (si retenue) reproduit fidèlement un cas de test
  connu, sans `eval()`/`exec()` non sandboxé.
- **Risques** : sécurité d'un DSL mal sandboxé — voir `SECURITY_AND_OPERATIONS.md`.
- **Rollback** : les stratégies Python restent le chemin de référence, DSL additif si retenu.
- **Tests** : `/tdd`, comparaison DSL vs Python sur `perfect_revolution_v1.py`.
- **Effort** : L à XL selon décision.
- **Compétences** : conception de langage, sécurité applicative.
- **Skills Claude Code recommandés** : `domain-modeling`, `tdd`, `implement`, `code-review`.
- **Hors périmètre explicite** : génération de stratégies par IA (explicitement repoussée par
  l'utilisateur).

## Phase 7 — Options

- **Objectif** : module options isolé (ADR 0011) — chaînes d'options, Greeks, valorisation,
  stratégies multi-jambes.
- **Prérequis** : aucun couplage requis avec les phases précédentes (isolation voulue), mais
  bénéficie d'une infrastructure stable (Phase 1) et d'un moteur de validation robuste (Phase 3)
  pour ses propres tests.
- **Dépendances** : ADR 0011.
- **Livrables** : `OptionContract`/`OptionChain`/`OptionStrategy` (voir `DOMAIN_MODEL.md` §8),
  distinction explicite des 4 catégories de données d'options.
- **Critères d'entrée** : Phase 1 terminée (infrastructure générique disponible).
- **Critères de sortie** : un backtest sur options théoriques reconstruites produit un résultat
  cohérent, clairement étiqueté comme théorique.
- **Risques** : disponibilité et coût des données d'options réelles — voir `RISK_REGISTER.md`.
- **Rollback** : module isolé, un échec ici n'affecte jamais le moteur spot (par construction,
  ADR 0011).
- **Tests** : `/tdd`.
- **Effort** : XL.
- **Compétences** : finance des produits dérivés, modèles de valorisation.
- **Skills Claude Code recommandés** : `domain-modeling`, `codebase-design`, `tdd`, `implement`.
- **Hors périmètre explicite** : bloquer le déploiement serveur ou la robustesse du moteur spot
  (interdiction explicite de l'utilisateur).

## Phase 8 — Durcissement et éventuelle commercialisation

- **Objectif** : authentification, utilisateurs, rôles, audit, conformité, support — **uniquement
  si la commercialisation est explicitement décidée**.
- **Prérequis** : toutes les phases précédentes stables.
- **Dépendances** : ADR 0012 (environnements), `SECURITY_AND_OPERATIONS.md`.
- **Livrables** : selon décision — non détaillés ici tant que la commercialisation n'est pas
  engagée (voir `DECISION_BACKLOG.md`).
- **Critères d'entrée** : décision explicite de l'utilisateur d'engager la commercialisation.
- **Critères de sortie** : à définir au moment de la décision.
- **Risques** : conformité légale (non traitée dans cette mission, hors compétence
  architecturale pure).
- **Rollback** : sans objet tant que non engagée.
- **Tests** : à définir.
- **Effort** : XL.
- **Compétences** : sécurité applicative, conformité, produit.
- **Skills Claude Code recommandés** : à déterminer au moment de l'engagement.
- **Hors périmètre explicite de cette mission et des phases précédentes** : facturation, comptes
  utilisateurs, tout ce qui suppose une décision de commercialisation non prise.

---

## Prochaine action unique proposée

> **Phase 0 — préparation Oracle Cloud et portabilité Linux : exécuter l'audit Linux en
> conditions réelles, dockeriser localement, préparer les protections de coût, puis benchmarker
> sur OCI.**

Voir `docs/roadmap/EPICS_AND_TICKETS.md` (tickets `PH0-OCI-01` à `PH0-OCI-10`) pour le détail, et
la fin du compte rendu de cette mission pour un prompt prêt à copier dans une nouvelle session.
