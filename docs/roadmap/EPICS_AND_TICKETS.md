# Epics et tickets

> Voir `docs/INDEX.md` pour la navigation. Produit via le skill `to-tickets`, adapté à cette
> mission : un document consolidé unique (pas de publication GitHub Issues ni de fichiers
> `.scratch/` — décision explicite de l'utilisateur pour cette mission de planification). Tickets
> précis pour les Phases 0 et 1 ; macroscopiques au-delà. Un ticket bloqué par une décision non
> prise référence explicitement `DECISION_BACKLOG.md` ou l'ADR concernée — jamais de fausse
> précision sur un travail qui dépend encore d'un choix non tranché.

## Epics par phase

| Epic | Phase | Résumé | Bloqué par |
|---|---|---|---|
| **E0 — Architecture, Oracle Cloud et préparation** | 0 | Documents d'architecture, ADR (dont [ADR 0015](../adr/0015-oracle-cloud-infrastructure-payg.md) — Oracle Cloud Infrastructure PAYG retenu), roadmap, benchmark local puis OCI, protections de coût | Aucune |
| **E1 — Serveur de staging OCI** | 1 | Docker Compose sur instance OCI, orchestrateur, Redis, PostgreSQL, stockage persistant OCI, secrets, HTTPS, sauvegardes, observabilité minimale, arrêt automatique | E0 (Go/No-Go validé) |
| **E2 — Industrialisation du Data Center** | 2 | Téléchargement incrémental, calendrier branché, provenance corrigée, corporate actions branchées | E0 (partiel), bénéficie de E1 |
| **E3 — Fiabilité scientifique** | 3 | Out-of-sample, walk-forward, Monte-Carlo, règles Champion formalisées | E2 |
| **E4 — Refonte UI/UX** | 4 | Décomposition `app.py`, design system, Playwright | E1, E2, E3 (services stables) |
| **E5 — Multi-actifs et portefeuille** | 5 | Modèle d'instruments étendu, portefeuille, exposition | E3 |
| **E6 — Éditeur de stratégies** | 6 | DSL ou hybride (selon ADR 0014), sécurité, versionnement | ADR 0014 tranchée |
| **E7 — Module Options** | 7 | Sous-système isolé (ADR 0011) | E1 (infrastructure générique) ; jamais bloquant pour les autres |
| **E8 — Durcissement / commercialisation** | 8 | Authentification, rôles, audit — **si décidé** | Décision explicite de l'utilisateur (`DECISION_BACKLOG.md`) |

---

## Phase 0 — tickets précis

### PH0-01 — Documents d'architecture et ADR de la Phase 0

**What to build** : l'ensemble des documents `docs/architecture/*.md`, `docs/roadmap/*.md`,
`docs/adr/0005-*.md` à `0015-*.md` (dont l'ADR Oracle Cloud), `docs/INDEX.md` — livrés par cette
mission.

**Blocked by** : Aucune — peut démarrer immédiatement.

**Contexte** : audit factuel du dépôt du 2026-08-06 (voir `docs/architecture/CURRENT_STATE.md`).

**Fichiers/modules concernés** : `docs/` uniquement, aucun fichier de code.

- [ ] Tous les documents listés existent et sont liés depuis `docs/INDEX.md`.
- [ ] Aucun ADR existant renuméroté.
- [ ] `/code-review` exécuté sur l'ensemble (conformité + cohérence architecturale).

**Tests attendus** : revue documentaire uniquement (`/code-review`), pas de test logiciel.
**Risques** : incohérence entre documents — mitigé par la revue finale.
**Rollback** : sans objet (documentation, aucun système modifié).
**Estimation** : L.
**Skills recommandés** : `codebase-design`, `domain-modeling`, `to-tickets`, `code-review`.
**Autorisations manuelles requises** : aucune (documentation).
**Statut** : ready-for-agent (déjà largement réalisé par cette mission elle-même).

### PH0-02 et PH0-03 — remplacés par PH0-OCI-03/09/10 ci-dessous

Depuis la décision [ADR 0015](../adr/0015-oracle-cloud-infrastructure-payg.md) (Oracle Cloud
Infrastructure PAYG retenu), le fournisseur n'est plus un choix ouvert entre plusieurs serveurs
dédiés loués à l'essai (ancienne portée de PH0-02/PH0-03) — le protocole de benchmark est
maintenant exécuté d'abord localement puis sur OCI, et le choix se limite au dimensionnement du
profil OCI. **PH0-02 et PH0-03 sont retirés en tant que tickets autonomes** ; leur contenu est
repris et précisé par PH0-OCI-03 (définir le benchmark), PH0-OCI-09 (exécuter le benchmark OCI) et
PH0-OCI-10 (choisir la forme finale de VM) ci-dessous — pas de doublon, pas de perte d'exigence.

### PH0-OCI-01 — Valider la portabilité Linux en conditions réelles

**What to build** : confirmation, sur une instance Linux réelle (OCI, palier gratuit suffisant),
que le pipeline existant (`app.py`, `engine.py`, `job_launcher.py`, `optimizer_process.py`,
`requirements-server.txt`) s'installe et s'exécute sans adaptation majeure.

**Blocked by** : PH0-01 (documents d'architecture, dont `CURRENT_STATE.md` §3, déjà livré).

**Contexte** : l'audit du 2026-08-06 (`CURRENT_STATE.md` §3) n'a trouvé aucune dépendance
Windows dure dans le pipeline applicatif (seuls `get_data.py`/`check_mt5.py`, non importés par
l'app, et `metatrader5` dans `requirements.txt`, déjà absent de `requirements-server.txt`) — ce
ticket **vérifie** cette conclusion en conditions réelles, il ne repart pas de zéro.

**Fichiers/modules concernés** : initialement, aucun changement de code prévu (audit seul). Un
bug réel trouvé pendant l'audit a été traité séparément, comme prévu, dans le ticket dédié
`PH0-OCI-01-BUG` ci-dessous (`optimization_store.py`, `optimizer_process.py`) — autorisé
explicitement dans une session ultérieure. Corrections de portabilité A-E dans `.streamlit/
config.toml`, `lancer_app.bat`, `pytest.ini` (nouveau), `lancer_app.sh` (nouveau),
`.gitattributes` (nouveau).

**Statut : Implémentation corrective terminée — validation Linux réelle OCI restante.**

**État (audit du 2026-08-06, corrections du 2026-08-07, voir [`LINUX_PORTABILITY_REPORT.md`](../architecture/LINUX_PORTABILITY_REPORT.md))** :
Docker/WSL2/CI se sont révélés indisponibles sur le poste de développement — l'exécution réelle
sur instance Linux n'a toujours pas pu avoir lieu (aucune ressource OCI créée, hors périmètre des
deux sessions). Réalisé à la place : audit statique exhaustif (32 catégories, aucun bloquant),
vérification réelle de résolution des wheels Linux via `pip download --platform` (tous les
paquets de `requirements-server.txt` résolvent), 14 tests dynamiques légers sous Windows
(14/14), **puis correction et validation d'un bug réel trouvé pendant l'audit** (reprise de job
`resume_run_id` silencieusement cassée en mode job-directory — voir `PH0-OCI-01-BUG` ci-dessous)
et des 4 corrections de portabilité applicables sans machine Linux (Streamlit headless,
encodage explicite, configuration pytest, lanceur `.sh`, `.gitattributes`). Décision : **Go
conditionnel, inchangée** — reste uniquement l'exécution réelle sur instance OCI.

- [x] Portabilité confirmée par audit statique + résolution réelle des dépendances Linux
      (`pip download --platform`) — voir rapport, aucun bloquant.
- [x] Tests légers exécutés (import, chemins, job directory, JSON, backtest, optimisation,
      Streamlit headless, secrets, chemins absolus) — 14/14, sous Windows (limite documentée).
- [x] **Bug de reprise de job (`resume_run_id`) corrigé et testé** (`tests/test_job_resume.py`,
      11 tests, rouge avant/vert après) — voir ticket `PH0-OCI-01-BUG` ci-dessous.
- [x] Corrections de portabilité A-D appliquées (Streamlit headless, encodage UTF-8 explicite,
      `pytest.ini`, `lancer_app.sh`) + E (`.gitattributes`) — suite complète 546/546 verte.
- [ ] `pip install -r requirements-server.txt` réussit **réellement** sur une instance OCI —
      **non exécuté**, aucune ressource OCI créée (hors périmètre des deux sessions).
- [ ] `app.py` démarre et sert l'interface (mode `headless=true`) **réellement sur OCI** — non
      exécuté.
- [ ] Un backtest simple s'exécute sur OCI et produit un résultat identique (aux flottants près)
      à l'exécution locale Windows de référence — non exécuté.
- [ ] `lancer_app.sh` exécuté réellement sous Linux (droit d'exécution à positionner au commit,
      Windows ne peut pas écrire le bit Unix) — non exécuté.

**Tests attendus** : comparaison du résultat OCI vs résultat Windows de référence, procédure
détaillée en section 11 du rapport de portabilité.
**Risques** : un blocage Linux non anticipé retarderait la Phase 0 — risque réduit par l'audit
statique, la vérification réelle des dépendances et la correction du bug de reprise (aucun signal
négatif restant), mais pas éliminé tant que l'exécution réelle sur OCI n'a pas eu lieu.
**Rollback** : sans objet pour la partie validation. Pour les corrections de code : `git diff`
localisé (2 fichiers de code modifiés, voir compte rendu), aucun format de fichier historique
changé.

### PH0-OCI-01-BUG — Reprise de job (`resume_run_id`) cassée en mode job-directory

**What to build** : `resume_run_id` doit retrouver les combinaisons déjà testées d'un job source
(`results/{resume_run_id}/tested.json`) et ne pas les recalculer.

**Blocked by** : PH0-OCI-01 (audit, qui a découvert ce bug).

**Contexte** : trouvé pendant l'audit de portabilité, pas une régression de cette session — le
mécanisme existait mais n'avait jamais été testé en conditions réelles du pipeline
`results/job_xxx/` avant `LINUX_PORTABILITY_REPORT.md`.

- [x] Test de reproduction écrit et rouge avant correction
      (`tests/test_job_resume.py::TestJobResumeEndToEnd::test_resume_finds_combinations_already_tested_by_a_prior_job`).
- [x] Cause exacte identifiée : `load_tested_hashes(config.resume_run_id)` sans `job_dir`
      résolvait vers `optimization_history/` au lieu du dossier frère `results/{resume_run_id}/`.
- [x] Correction minimale appliquée : `optimization_store.resolve_sibling_job_dir()` (nouvelle
      fonction pure, ne crée aucun répertoire) + un appel modifié dans `optimizer_process.py`.
- [x] Test vert après correction, 11/11 tests du fichier passent, aucune régression sur les 535
      tests préexistants (546/546 au total).

**Tests attendus** : `tests/test_job_resume.py` (11 tests, dont reproduction bout en bout via
subprocess réel, cas négatifs — inexistant/sans résultat/partiel/pas de collision — et
non-régression du mode classique).
**Risques** : aucun risque résiduel identifié — correction localisée, testée, comportement hors
reprise inchangé (test dédié).
**Rollback** : `git diff optimization_store.py optimizer_process.py` — 2 fichiers, changement
minimal, facilement réversible si besoin.
**Skills utilisés** : `tdd`, `implement`, `code-review`.
**Autorisations manuelles requises** : aucune supplémentaire — correction couverte par
l'autorisation explicite donnée pour cette session.
**Estimation** : S.
**Skills recommandés** : aucun skill Claude Code spécifique — exécution manuelle supervisée.
**Autorisations manuelles requises** : création d'une instance OCI (palier Always Free) —
autorisation explicite requise avant toute création de ressource cloud.

### PH0-OCI-02 — Préparer un squelette Docker Compose local

**What to build** : un `docker-compose.yml` **local** (poste de développement, pas encore OCI)
démarrant l'interface Streamlit actuelle et une instance PostgreSQL vide, pour valider la
structure avant tout déploiement cloud.

**Blocked by** : PH0-OCI-01.

**Contexte** : [ADR 0009](../adr/0009-docker-compose-for-staging.md) (Docker Compose retenu),
[ADR 0007](../adr/0007-postgresql-for-metadata.md) (PostgreSQL). Ce squelette local est le point
de départ du squelette OCI de PH1-02 (portée staging), pas un doublon — PH0-OCI-02 valide la
structure sans dépendre d'une instance cloud.

- [ ] `docker-compose up` démarre l'interface en local, accessible sur `localhost`.
- [ ] Aucun secret dans l'image ni dans le dépôt (fichier `.env` local non versionné).

**Tests attendus** : l'interface actuelle (backtest simple) fonctionne à l'identique sur ce
squelette local.
**Risques** : sur-ingénierie prématurée si le squelette anticipe des services non encore décidés
(Redis, workers) — s'en tenir à interface + PostgreSQL pour ce ticket.
**Rollback** : sans objet (additif, n'affecte pas l'exécution locale existante).
**Estimation** : S.
**Skills recommandés** : `implement`, `code-review` (autorisation de modifier du code requise en
son temps — hors périmètre strict de cette mission de planification).
**Autorisations manuelles requises** : création des fichiers Docker — hors périmètre de cette
mission de planification, autorisation explicite requise en son temps.

### PH0-OCI-03 — Définir le benchmark reproductible (local puis OCI)

**What to build** : le protocole de benchmark de `docs/roadmap/BENCHMARK_PLAN.md` §1, instancié
en scripts/procédure reproductible exécutable d'abord en local (référence), puis identique sur
OCI.

**Blocked by** : PH0-OCI-02.

**Contexte** : reprend et précise l'ancien PH0-02 (voir note de remplacement ci-dessus) — le
protocole lui-même (tailles de données, combinaisons, workers, mesures) est déjà défini dans
`BENCHMARK_PLAN.md` §1, ce ticket produit la procédure d'exécution reproductible, pas un nouveau
protocole.

- [ ] Le protocole s'exécute de bout en bout en local et produit les mesures attendues
      (temps, CPU, RAM, E/S) de façon reproductible (deux exécutions locales donnent des mesures
      cohérentes).

**Tests attendus** : deux exécutions locales consécutives du même scénario donnent des mesures
dans une marge de variance acceptable (à définir).
**Risques** : mesures faussées par d'autres charges sur la machine — isoler l'exécution.
**Rollback** : sans objet.
**Estimation** : M.
**Skills recommandés** : aucun skill Claude Code spécifique.
**Autorisations manuelles requises** : aucune pour la partie locale.

### PH0-OCI-04 — Définir le stockage persistant OCI

**What to build** : décision motivée Block Volume vs Object Storage par type de donnée (brut
EODHD, normalisé Parquet, résultats de jobs, sauvegardes PostgreSQL) — voir
`docs/roadmap/DECISION_BACKLOG.md`.

**Blocked by** : PH0-OCI-01.

**Contexte** : [ADR 0008](../adr/0008-market-data-storage-strategy.md) fixe déjà la stratégie
générale (raw immuable/normalisé Parquet/dérivé) ; ce ticket l'instancie spécifiquement sur les
primitives OCI (Block Volume pour l'accès fréquent, Object Storage pour l'archivage/sauvegarde
probablement — à confirmer par étude technique, pas encore tranché).

- [ ] Chaque type de donnée listé dans `DATA_ARCHITECTURE.md` a une primitive OCI assignée
      (Block Volume ou Object Storage), documentée.

**Tests attendus** : sans objet (décision documentée).
**Risques** : mauvais choix initial coûteux à migrer — mitigé en documentant explicitement la
réversibilité de chaque choix.
**Rollback** : sans objet.
**Estimation** : S.
**Skills recommandés** : `WebSearch`/`WebFetch` (documentation officielle Oracle).
**Autorisations manuelles requises** : aucune (décision documentée, pas de ressource créée).
**Décision liée** : `DECISION_BACKLOG.md` — "Block Volume ou Object Storage par type de donnée".

### PH0-OCI-05 — Définir les secrets et permissions OCI

**What to build** : mécanisme de gestion des secrets sur OCI (variables d'environnement injectées
au démarrage, ou OCI Vault) et permissions minimales du compte de service utilisé par
l'application.

**Blocked by** : PH0-OCI-01.

**Contexte** : `docs/architecture/SECURITY_AND_OPERATIONS.md` §1-2 — règles déjà respectées en
local pour EODHD/IG, à étendre à OCI (clé API OCI elle-même, secrets applicatifs).

- [ ] Aucun secret OCI ni applicatif dans le dépôt ou dans une image Docker.
- [ ] Le compte/rôle OCI utilisé a des permissions minimales (pas de rôle administrateur complet
      pour l'application).

**Tests attendus** : vérification manuelle qu'aucun secret n'apparaît dans les logs/erreurs.
**Risques** : voir `RISK_REGISTER.md` — "Fuite de secrets".
**Rollback** : sans objet (mesure de sécurité additive).
**Estimation** : S.
**Skills recommandés** : `code-review` (axe sécurité).
**Autorisations manuelles requises** : création d'un compte/rôle OCI de service — autorisation
explicite requise.

### PH0-OCI-06 — Définir l'arrêt automatique

**What to build** : mécanisme technique d'arrêt automatique après inactivité et d'arrêt forcé
après durée maximale, indépendant des alertes budgétaires (voir
`SECURITY_AND_OPERATIONS.md` §7 — "principe non négociable").

**Blocked by** : PH0-OCI-01.

**Contexte** : cycle à la demande décrit dans `docs/architecture/COMPUTE_AND_JOBS.md` §6, étape
10. Ce ticket définit **comment** (API OCI, script planifié, autre), sans encore l'implémenter.

- [ ] Mécanisme documenté vérifiant l'absence de travail en file/en cours avant d'arrêter une
      instance.
- [ ] Mécanisme de secours (arrêt forcé après durée maximale) indépendant du premier.

**Tests attendus** : sans objet à ce stade (conception, pas implémentation).
**Risques** : arrêt déclenché à tort pendant un job encore utile — voir mitigation dans
`COMPUTE_AND_JOBS.md` §6.
**Rollback** : sans objet.
**Estimation** : M.
**Skills recommandés** : `codebase-design`.
**Autorisations manuelles requises** : aucune pour la conception.
**Décision liée** : `DECISION_BACKLOG.md` — "Mécanisme exact de démarrage/arrêt des workers OCI".

### PH0-OCI-07 — Définir les protections budgétaires

**What to build** : estimation de coût avant campagne, quotas (workers max, vCPU max, durée max
de job), alertes budgétaires, journal des heures de calcul, tableau de consommation, confirmation
utilisateur avant opération coûteuse, procédure d'arrêt d'urgence — liste complète dans
`SECURITY_AND_OPERATIONS.md` §7.

**Blocked by** : PH0-OCI-06 (l'arrêt automatique est le mécanisme technique complémentaire, pas
un substitut).

**Contexte** : principe explicite de l'utilisateur — "les alertes budgétaires ne doivent pas être
considérées comme l'unique protection".

- [ ] Chacune des 12 exigences de `SECURITY_AND_OPERATIONS.md` §7 a un mécanisme défini (pas
      nécessairement implémenté).

**Tests attendus** : sans objet à ce stade (conception).
**Risques** : facture imprévue si ce ticket n'est pas terminé avant PH0-OCI-09 (benchmark OCI
réel) — **dépendance explicite, ne pas exécuter de benchmark payant avant.**
**Rollback** : sans objet.
**Estimation** : M.
**Skills recommandés** : `codebase-design`.
**Autorisations manuelles requises** : aucune pour la conception.

### PH0-OCI-08 — Préparer le déploiement de staging

**What to build** : checklist de préparation (secrets, stockage, réseau, Docker Compose local
validé) confirmant que tout est prêt pour un déploiement OCI réel, sans encore le faire.

**Blocked by** : PH0-OCI-02, PH0-OCI-04, PH0-OCI-05, PH0-OCI-06, PH0-OCI-07.

**Contexte** : porte d'entrée vers la Phase 1 (`docs/roadmap/MASTER_ROADMAP.md`, critères Go/No-Go
de la Phase 0).

- [ ] Checklist Go/No-Go de `MASTER_ROADMAP.md` (Phase 0) entièrement cochée.

**Tests attendus** : sans objet (checklist).
**Risques/Rollback** : sans objet.
**Estimation** : S.
**Skills recommandés** : `code-review`.
**Autorisations manuelles requises** : aucune (vérification).

### PH0-OCI-09 — Exécuter le benchmark OCI (ultérieurement)

**What to build** : résultats mesurés (temps, CPU, RAM, E/S) pour la matrice définie dans
`BENCHMARK_PLAN.md` §1, exécutés réellement sur une instance OCI payante.

**Blocked by** : PH0-OCI-03 (protocole reproductible défini), PH0-OCI-07 (protections
budgétaires **impérativement en place avant**).

**Contexte** : reprend et précise l'ancien PH0-02 (voir note de remplacement ci-dessus), ciblé
spécifiquement sur OCI plutôt que sur "au moins un fournisseur" générique.

- [ ] Les 3 tailles de données × 3 volumes de combinaisons × 4 niveaux de workers sont mesurés
      sur au moins une forme OCI (`E5.Flex` recommandé).
- [ ] Les résultats sont consignés (annexe à `BENCHMARK_PLAN.md`, hors périmètre de cette
      mission).
- [ ] L'instance de benchmark est explicitement détruite après usage (pas laissée active).

**Tests attendus** : sans objet (mesure).
**Risques** : facture imprévue si PH0-OCI-07 n'est pas terminé — voir dépendance explicite.
**Rollback** : détruire l'instance si les résultats ne justifient pas la poursuite.
**Estimation** : M.
**Skills recommandés** : aucun skill Claude Code spécifique — exécution manuelle supervisée.
**Autorisations manuelles requises** : dépense financière réelle (instance OCI payante) —
autorisation explicite de l'utilisateur requise avant exécution, conformément aux règles de
sécurité de ce dépôt.

### PH0-OCI-10 — Choisir la forme finale de VM après benchmark

**What to build** : décision finale du profil OCI (forme, OCPU, RAM) pour le staging, avec preuve
issue de PH0-OCI-09.

**Blocked by** : PH0-OCI-09.

**Contexte** : reprend et précise l'ancien PH0-03 (voir note de remplacement ci-dessus).

- [ ] Profil choisi documenté avec les mesures qui le justifient (référence au benchmark).
- [ ] `requirements-server.txt` installé et validé sur la forme choisie (au-delà de la validation
      minimale de PH0-OCI-01).

**Tests attendus** : `pip install -r requirements-server.txt` réussit sur la forme finale.
**Risques** : voir `RISK_REGISTER.md` — "Coûts serveur imprévus".
**Rollback** : ajuster le profil (formes flexibles OCI, pas de nouvelle commande nécessaire).
**Estimation** : S.
**Skills recommandés** : `WebSearch`/`WebFetch` (revérifier les prix avant tout engagement).
**Autorisations manuelles requises** : engagement de dépense récurrente (staging permanent),
autorisation explicite requise.

---

## Phase 1 — tickets précis

> Prérequis de phase : Phase 0 terminée avec critères Go/No-Go validés (voir
> `MASTER_ROADMAP.md`). Les tickets ci-dessous supposent qu'une instance OCI de staging peut être
> créée dans le respect des protections de coût déjà définies en PH0-OCI-06/07.

### PH1-01 — Prototype file de travaux (RQ vs Celery)

**What to build** : deux prototypes minimaux (un job factice publié/consommé) démontrant le
comportement de reprise après crash, le suivi de progression, et l'annulation, pour RQ et pour
Celery.

**Blocked by** : PH0-OCI-08 (déploiement de staging prêt) — remplace l'ancien PH0-03, retiré.

**Contexte** : ADR 0006 (`Decision pending`) — aucune décision technologique prise avant preuve.

- [ ] Les deux prototypes tournent sur le serveur de staging.
- [ ] Le tableau comparatif de `docs/architecture/COMPUTE_AND_JOBS.md` §1 est complété avec des
      mesures réelles (pas seulement des critères qualitatifs).
- [ ] ADR 0006 mise à jour en statut Accepted avec la décision et ses preuves.

**Tests attendus** : test de reprise après `kill -9` d'un worker en cours de traitement.
**Risques** : voir `RISK_REGISTER.md` — "Jobs perdus".
**Rollback** : rester sur le système `subprocess.Popen` actuel si aucune option ne convainc.
**Estimation** : M.
**Skills recommandés** : `tdd`, `implement` (une fois le code de prototype autorisé —
hors périmètre strict de cette mission de planification).
**Autorisations manuelles requises** : autorisation explicite de modifier du code (hors
périmètre de la mission actuelle, purement architecture).
**Décision liée** : `DECISION_BACKLOG.md` — "RQ ou Celery".

### PH1-02 — Squelette Docker Compose (interface + PostgreSQL, sans workers)

**What to build** : un `docker-compose.yml` minimal démarrant l'interface Streamlit actuelle
(`app.py` inchangé) et une instance PostgreSQL vide, accessible en HTTPS sur l'instance OCI de
staging via un reverse proxy — étend le squelette local de PH0-OCI-02 à l'instance OCI réelle.

**Blocked by** : PH0-OCI-08 (déploiement de staging prêt) — remplace l'ancien PH0-03, retiré.

**Contexte** : ADR 0009 (Docker Compose staging), ADR 0007 (PostgreSQL métadonnées).

- [ ] `docker-compose up` démarre l'interface, accessible via HTTPS.
- [ ] `.streamlit/config.toml` `headless` passé à `true` pour l'environnement serveur (sans
      casser l'usage local — via variable d'environnement ou fichier de config séparé).
- [ ] Aucun secret dans l'image Docker ni dans le dépôt.

**Tests attendus** : l'interface actuelle (backtest simple) fonctionne à l'identique sur ce
squelette.
**Risques** : voir `RISK_REGISTER.md` — "Complexité prématurée" (mitigé : squelette minimal
d'abord, pas tout le système d'un coup).
**Rollback** : revenir à l'exécution locale, le squelette Docker est additif.
**Estimation** : M.
**Skills recommandés** : `implement`, `code-review`.
**Autorisations manuelles requises** : autorisation explicite de créer les fichiers Docker et de
modifier la configuration Streamlit (hors périmètre de cette mission de planification).

### PH1-03 — Orchestrateur publie sur la file de travaux (remplace `subprocess.Popen` local)

**What to build** : `job_launcher.py` (ou un successeur) publie un travail sur la file choisie
(PH1-01) au lieu de lancer directement un `subprocess.Popen`, tout en préservant le contrat de
job directory à l'identique.

**Blocked by** : PH1-01 (technologie tranchée), PH1-02 (infrastructure de base disponible).

**Contexte** : ADR 0005 (monolithe modulaire + workers).

- [ ] Un job lancé depuis l'UI produit exactement les mêmes fichiers qu'aujourd'hui
      (`progress.json`, `results.csv`, etc.).
- [ ] `assert_no_active_jobs()` est remplacé par une limite de concurrence configurable (pas
      supprimé sans remplacement).
- [ ] Les tests `test_e2e_subprocess.py`/`test_e2e_parallel.py` sont adaptés et passent sur le
      nouveau chemin.

**Tests attendus** : `/tdd` — tests de non-régression sur le contrat de fichiers, test de
publication/consommation via la file.
**Risques** : régression du verrou de concurrence actuel — mitigé par des tests explicites avant
suppression de `assert_no_active_jobs()`.
**Rollback** : garder le chemin `subprocess.Popen` local disponible en repli (flag de
configuration) jusqu'à validation complète du nouveau chemin.
**Estimation** : L.
**Skills recommandés** : `tdd`, `implement`, `code-review`.
**Autorisations manuelles requises** : modification de code d'orchestration — hors périmètre de
cette mission de planification, autorisation explicite requise en son temps.

### PH1-04 — Workers de calcul sur le serveur, backtest + optimisation

**What to build** : au moins un worker backtest et un worker optimisation tournant en conteneur,
consommant la file de travaux, écrivant sur le volume NVMe du serveur.

**Blocked by** : PH1-03.

- [ ] Un job de bout en bout (backtest simple + optimisation réduite) s'exécute entièrement sur
      le serveur, résultat téléchargeable depuis l'UI.

**Tests attendus** : reprise de `test_e2e_parallel.py` adapté au contexte serveur.
**Risques/Rollback** : voir PH1-03.
**Estimation** : M.
**Skills recommandés** : `implement`, `code-review`.
**Autorisations manuelles requises** : idem PH1-03.

### PH1-05 — Secrets serveur (EODHD, IG, PostgreSQL, Redis)

**What to build** : gestion des secrets serveur par variables d'environnement injectées au
démarrage des conteneurs, jamais dans l'image ni dans le dépôt.

**Blocked by** : PH1-02.

**Contexte** : `docs/architecture/SECURITY_AND_OPERATIONS.md` §1-2 — règles déjà respectées côté
EODHD/IG local, à étendre au serveur.

- [ ] Aucun secret visible dans `docker-compose.yml` versionné (fichier `.env` non versionné ou
      coffre de secrets).
- [ ] Statut "configuré/non configuré" affichable sans jamais exposer la valeur.

**Tests attendus** : vérification manuelle qu'aucun secret n'apparaît dans les logs/erreurs.
**Risques** : voir `RISK_REGISTER.md` — "Fuite de secrets".
**Rollback** : sans objet (mesure de sécurité additive).
**Estimation** : S.
**Skills recommandés** : `code-review` (axe sécurité).
**Autorisations manuelles requises** : accès aux vraies clés EODHD/IG pour configurer le serveur
— déjà géré avec prudence par l'utilisateur jusqu'ici, même précaution à conserver.

### PH1-06 — HTTPS via reverse proxy

**What to build** : Caddy ou Nginx (choix en `DECISION_BACKLOG.md`) devant l'interface, HTTPS
actif.

**Blocked by** : PH1-02.

- [ ] L'interface est accessible uniquement en HTTPS, jamais en HTTP non chiffré depuis
      l'extérieur du serveur.

**Tests attendus** : vérification manuelle du certificat.
**Risques/Rollback** : faibles, mesure additive standard.
**Estimation** : S.
**Skills recommandés** : `implement`.
**Autorisations manuelles requises** : nom de domaine/DNS si HTTPS public (à clarifier avec
l'utilisateur le moment venu).

### PH1-07 — Sauvegarde et restauration testées

**What to build** : dump PostgreSQL planifié + sauvegarde sélective de fichiers critiques, avec
une restauration **réellement testée** au moins une fois.

**Blocked by** : PH1-02, PH1-04 (données réelles à sauvegarder).

- [ ] Une restauration complète depuis la sauvegarde reproduit un état fonctionnel.

**Tests attendus** : exercice de restauration en conditions contrôlées (pas en production).
**Risques** : voir `RISK_REGISTER.md` — "Perte de sauvegarde" (le risque que cette tâche mitige).
**Rollback** : sans objet.
**Estimation** : M.
**Skills recommandés** : `implement`.
**Autorisations manuelles requises** : accès au serveur pour l'exercice de restauration.

### PH1-08 — Observabilité minimale

**What to build** : logs structurés par job (déjà partiellement le cas via `logs.txt`), métriques
CPU/RAM/disque du serveur, alerte simple si un job ne progresse plus.

**Blocked by** : PH1-04.

- [ ] Un job bloqué est détectable en moins d'un seuil défini (ex. 10 minutes sans mise à jour de
      `progress.json`).

**Tests attendus** : simuler un job bloqué, vérifier la détection.
**Risques/Rollback** : faibles.
**Estimation** : M.
**Skills recommandés** : `implement`.
**Autorisations manuelles requises** : aucune particulière.

---

## Phases 2 à 8 — epics avec tickets macroscopiques

### Phase 2 — Industrialisation du Data Center

- **T-DC-1** — Corriger `job_store.write_data_manifest()` pour relier le vrai `content_hash`
  (EODHD ou CSV local). Bloqué par : ADR 0008 acceptée.
- **T-DC-2** — Brancher `detect_missing_trading_days()` sur un vrai contrôle qualité de
  production. Bloqué par : ADR 0013 acceptée.
- **T-DC-3** — Paramètre calendrier optionnel dans `market_data.resample`. Bloqué par : T-DC-2.
- **T-DC-4** — Reprise après interruption du téléchargement EODHD (checkpoint par fenêtre).
  Bloqué par : aucune décision ouverte identifiée — peut démarrer après Phase 1.
- **T-DC-5** — Suivi de quota cumulatif côté client EODHD. Bloqué par : aucune.
- **T-DC-6** — Brancher dividendes/splits/titres radiés au catalogue. Bloqué par : ADR 0007
  (catalogue PostgreSQL) recommandé mais pas strictement bloquant.
- **T-DC-7** — Migrer `settings/data_catalog.json` (code mort) vers PostgreSQL. Bloqué par :
  PH1-02 (PostgreSQL disponible).

### Phase 3 — Fiabilité scientifique

- **T-VAL-1** — Audit ciblé du look-ahead bias dans `engine.py`/`on_bar()`. Bloqué par : aucune.
- **T-VAL-2** — Période out-of-sample (jamais utilisée avant verdict final). Bloqué par : T-DC-1
  (provenance fiable nécessaire pour crédibiliser les résultats).
- **T-VAL-3** — Moteur walk-forward. Bloqué par : T-VAL-2.
- **T-VAL-4** — Moteur Monte-Carlo. Bloqué par : T-VAL-2.
- **T-VAL-5** — Formalisation des règles Champion (`/domain-modeling` avec l'utilisateur). Bloqué
  par : T-VAL-3, T-VAL-4.
- **T-VAL-6** — Modèle d'exécution réaliste (commission, latence, financement overnight, gaps).
  Bloqué par : aucune décision ouverte, mais dépend de priorisation utilisateur.

### Phase 4 — Refonte UI/UX

- **T-UI-1** à **T-UI-N** — un ticket par onglet migré (Maintenance, Historique manuel, Data
  Center déjà fait, Optimisation en dernier — voir ADR 0010). Chaque ticket bloqué par la
  stabilité du backend qu'il consomme (Phase 1-3 selon l'onglet).
- **T-UI-DESIGN** — Design system formalisé (tokens, composants). Bloqué par : aucune (peut être
  préparé en parallèle, voir `DEPENDENCY_MAP.md` règle 5).

### Phase 5 — Multi-actifs et portefeuille

- **T-MA-1** — Audit du couplage mono-actif réel de `engine.py` (avant tout chiffrage précis).
  Bloqué par : Phase 3 terminée.
- **T-MA-2** — Modèle d'instrument étendu par classe d'actif. Bloqué par : T-MA-1.
- **T-MA-3** — `Portfolio`, exposition, allocation. Bloqué par : T-MA-2.

### Phase 6 — Éditeur de stratégies

- **T-DSL-1** — Prototype DSL minimal reproduisant `perfect_revolution_v1.py`. Bloqué par :
  décision préalable non requise pour un prototype (mais la généralisation l'est — voir ADR 0014).
- **T-DSL-2** — Décision ADR 0014 tranchée avec preuves du prototype.
- **T-DSL-3** — Implémentation complète (DSL ou hybride) si retenue. Bloqué par : T-DSL-2.

### Phase 7 — Module Options

- **T-OPT-1** — Modèle de domaine `OptionContract`/`OptionChain`. Bloqué par : Phase 1
  (infrastructure générique disponible).
- **T-OPT-2** — Étude des sources de données d'options réelles disponibles (coût, couverture).
  Bloqué par : `DECISION_BACKLOG.md` — "Options historiques réelles ou théoriques".
- **T-OPT-3** — Moteur de valorisation théorique (Black-Scholes ou équivalent). Bloqué par :
  T-OPT-1.

### Phase 8 — Durcissement / commercialisation

- **T-HARD-1** — Authentification et rôles. Bloqué par : décision explicite de commercialisation
  (`DECISION_BACKLOG.md`).
- **T-HARD-2** — Audit de conformité. Bloqué par : T-HARD-1 et décision produit hors périmètre
  architectural de cette mission.

---

## Principe de non-précision

Aucun ticket des Phases 2 à 8 ci-dessus n'est estimé en jours/points — leur ordre de grandeur
(S/M/L/XL) est donné au niveau de la phase dans `MASTER_ROADMAP.md`, pas au niveau du ticket
individuel, tant qu'ils n'ont pas été affinés au moment de leur prise en charge réelle.
