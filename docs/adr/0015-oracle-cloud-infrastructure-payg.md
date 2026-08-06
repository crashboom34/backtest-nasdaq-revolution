# Oracle Cloud Infrastructure Pay As You Go pour le staging et le calcul à la demande

**Statut** : Accepted (Accepté — décision explicitement validée par l'utilisateur)
**Date** : 2026-08-06

## Contexte

`docs/roadmap/DECISION_BACKLOG.md` laissait ouverte la question « VPS mutualisé, cloud public ou
serveur dédié », avec un plan de benchmark (`BENCHMARK_PLAN.md`) comparant OVHcloud, Hetzner et
Scaleway — tous des serveurs dédiés facturés en continu, indépendamment de l'usage réel. L'usage
attendu (backtests/optimisations ponctuels, pas une charge permanente) rend un serveur dédié
facturé 24h/24 potentiellement disproportionné tant que l'intensité réelle d'usage n'est pas
mesurée. L'utilisateur a validé Oracle Cloud Infrastructure (OCI) en mode Pay As You Go (PAYG)
comme cible principale, avec Hetzner conservé comme repli conditionnel.

Caractéristiques OCI vérifiées via documentation officielle (`docs.oracle.com`, 2026-08-06) :
- Formes de calcul flexibles AMD `VM.Standard.E4.Flex`/`E5.Flex`/`E6.Flex` : OCPU et RAM
  dimensionnables indépendamment (1 à 126 OCPU selon la forme, jusqu'à 64 Go de RAM par OCPU) —
  [Compute Shapes](https://docs.oracle.com/en-us/iaas/Content/Compute/References/computeshapes.htm).
- Formes Ampere (ARM) `VM.Standard.A1.Flex`/`A2.Flex`/`A4.Flex` disponibles en parallèle, mêmes
  plages de dimensionnement, architecture différente (voir §5 sur la posture x86 vs ARM).
- Palier "Always Free" réel et permanent (pas seulement un essai) : jusqu'à 4 OCPU/24 Go RAM
  Ampere A1 (1 500 heures-OCPU + 9 000 heures-Go/mois, équivalent 2 OCPU + 12 Go en continu),
  200 Go de Block Volume, 10-20 Go d'Object Storage —
  [Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).
- Tarification à l'heure pour les formes payantes (Pay As You Go), sans engagement — figures
  précises par OCPU/Go-heure identifiées via recherche (sources Oracle citées par le moteur de
  recherche : `oracle.com/cloud/compute/pricing`, `blogs.oracle.com`) mais **non confirmées par
  fetch direct** de la page de tarification (bloquée par une protection anti-robot au moment de
  la vérification, comme déjà rencontré avec `labs.ig.com` plus tôt dans ce projet) — **à
  reconfirmer sur `oracle.com/cloud/price-list/` avant tout engagement financier réel**, jamais
  traité comme un prix garanti.

## Forces en présence

- **Besoin d'indépendance vis-à-vis du PC local** : l'ordinateur de l'utilisateur limite déjà la
  vitesse des optimisations (constat répété dans `docs/architecture/QUALITY_ATTRIBUTES.md`) — le
  calcul doit pouvoir s'exécuter indépendamment de sa disponibilité/puissance, sans dépendre d'un
  poste allumé en continu.
- Le besoin réel est un usage ponctuel et variable (sessions de backtest/optimisation), pas une
  charge permanente — le PAYG facture au plus près de l'usage réel, contrairement à un serveur
  dédié facturé en continu.
- Le palier Always Free permet de commencer à zéro coût pour le staging léger (interface,
  orchestrateur, PostgreSQL) avant d'engager un budget sur des workers de calcul.
- Le paiement à l'usage permet d'augmenter temporairement la puissance pour une grosse campagne
  puis de revenir au palier de base — pattern impossible avec un serveur dédié loué au mois.
- Hetzner reste structurellement pertinent si l'usage devient intensif et permanent : à débit
  constant élevé, un serveur dédié facturé au mois devient moins cher qu'un cloud PAYG équivalent
  — c'est précisément le critère de réévaluation de cette ADR (voir plus bas).
- Risque de dépendance fournisseur : OCI a ses propres primitives (formes de calcul, Block
  Volume, Object Storage) — cette ADR ne les fige pas en détail (voir "Ne fige pas encore"),
  pour limiter le couplage tant que l'architecture n'a pas prouvé son fonctionnement.

## Options évaluées

1. **Rester sur la comparaison OVHcloud/Hetzner/Scaleway (serveurs dédiés uniquement)**
   (`BENCHMARK_PLAN.md` initial) — cohérent avec un usage permanent et intensif, mais
   disproportionné tant que l'intensité réelle n'est pas mesurée ; facture fixe même les jours
   sans usage.
2. **AWS/Azure/GCP** — écartées sans évaluation détaillée : aucune preuve que leur modèle PAYG
   apporte un avantage décisif par rapport à OCI pour ce cas d'usage ; à ne pas réévaluer sans
   raison concrète (éviter la sur-ingénierie du choix d'hébergeur).
3. **Oracle Cloud Infrastructure Pay As You Go** (retenu) — palier Always Free réel pour démarrer,
   facturation à l'heure pour les workers de calcul à la demande, formes flexibles permettant
   d'ajuster précisément OCPU/RAM sans changer de gamme de serveur.

## Décision

**Oracle Cloud Infrastructure (OCI) en mode Pay As You Go est la cible principale** pour :
l'environnement de staging, les workers de calcul à la demande, l'exécution distante des
backtests/optimisations, le stockage persistant des données et résultats.

**Hetzner dédié reste une alternative conditionnelle** : à réévaluer si les benchmarks (voir
`BENCHMARK_PLAN.md`) montrent un usage suffisamment intensif et permanent pour qu'un serveur
dédié facturé au mois devienne plus avantageux qu'un cloud PAYG équivalent.

**OVHcloud et Scaleway restent documentés** dans `BENCHMARK_PLAN.md` à titre de repères de
marché, mais ne sont plus la cible principale de cette architecture.

### Principe de conception : séparation stricte calcul éphémère / stockage persistant

Cette décision impose un **seam explicite** entre deux modules aux propriétés radicalement
différentes :

- **Calcul éphémère (workers OCI)** — module à interface volontairement mince : un worker sait
  consommer un travail de la file, écrire sur le stockage persistant via son interface (chemin
  de montage ou API), et s'arrêter. Il ne détient **aucune donnée qui n'existerait qu'en lui** —
  test de suppression : détruire une instance de calcul ne doit jamais faire disparaître une
  donnée qui n'existe nulle part ailleurs.
- **Stockage persistant (Block Volume, Object Storage, PostgreSQL, sauvegardes)** — module
  profond : toute la complexité de durabilité, réplication, sauvegarde vit derrière une interface
  simple pour les workers (écrire un fichier, insérer une ligne). Test de suppression inverse :
  détruire ce module ferait disparaître des données réelles — c'est le signal qu'il porte
  légitimement la responsabilité de la persistance, contrairement au calcul éphémère.

Cette frontière doit rester visible dans `docs/architecture/DEPLOYMENT_ARCHITECTURE.md` (topologie)
et `docs/architecture/COMPUTE_AND_JOBS.md` (cycle de vie du worker à la demande) — jamais traitée
comme un détail d'implémentation secondaire.

## Conséquences positives

- Coût aligné sur l'usage réel, avec un palier gratuit pour commencer sans engagement.
- Possibilité de puissance temporaire pour une grosse campagne, sans repenser l'architecture.
- La séparation calcul/stockage, explicite dès cette ADR, prépare naturellement l'architecture
  évolutive multi-nœuds (`DEPLOYMENT_ARCHITECTURE.md` Niveau 2) sans réécriture.

## Conséquences négatives

- Complexité opérationnelle du cycle démarrage/arrêt des workers (voir
  `docs/architecture/COMPUTE_AND_JOBS.md` §6) — absente d'un serveur dédié toujours allumé.
- Risque de facture imprévue si le contrôle des coûts (voir
  `docs/architecture/SECURITY_AND_OPERATIONS.md` §7) n'est pas mis en place avant tout usage réel.
- Dépendance aux primitives spécifiques d'OCI (formes de calcul, Block Volume, Object Storage) —
  un futur changement de fournisseur ne serait pas gratuit.

## Risques

- **Facture imprévue** — mitigation : estimation de coût avant campagne, alertes budgétaires,
  arrêt automatique après inactivité, arrêt forcé après durée maximale (détail complet en
  `SECURITY_AND_OPERATIONS.md` §7) ; les alertes budgétaires ne sont **jamais** l'unique
  protection.
- **Arrêt automatique déclenché à tort** (pendant un job encore utile) — mitigation : le mécanisme
  d'arrêt doit vérifier l'absence de travail en file/en cours avant de couper une instance (détail
  en `COMPUTE_AND_JOBS.md` §6).
- **Dépendance fournisseur** — mitigation : le contrat de job directory et le stockage persistant
  restent, par conception, indépendants des primitives de calcul OCI (voir séparation ci-dessus) ;
  une migration vers Hetzner resterait limitée à la couche calcul.
- **Prix non garantis dans le temps** — mitigation : toute figure chiffrée de cette ADR et de
  `BENCHMARK_PLAN.md` est explicitement datée et à revérifier avant engagement, jamais présentée
  comme un tarif garanti.

## Plan de migration

1. Phase 0 (en cours) : benchmark local puis OCI sur le palier gratuit/PAYG, comparaison des
   profils (voir `BENCHMARK_PLAN.md`).
2. Phase 1 : premier déploiement de staging sur une seule instance OCI avec Docker Compose (voir
   `DEPLOYMENT_ARCHITECTURE.md` Niveau 1, mis à jour pour OCI).
3. Si Hetzner devient pertinent (voir critères de réévaluation) : seule la couche calcul migre,
   grâce à la séparation calcul/stockage actée dans cette ADR — le stockage persistant et le
   contrat de job directory ne changent pas.

## Critères de réévaluation

- Réévaluer Hetzner si le journal des heures de calcul (voir `SECURITY_AND_OPERATIONS.md` §7)
  montre un usage quasi permanent sur plusieurs semaines, au point qu'un serveur dédié facturé au
  mois deviendrait moins cher que l'équivalent PAYG mesuré.
- Réévaluer la forme de calcul (AMD vs Ampere ARM) uniquement après l'audit complet des
  dépendances Python et un benchmark comparatif dédié (voir `BENCHMARK_PLAN.md` §5) — jamais
  adopter ARM par défaut sans cette preuve.
- Ne pas rouvrir le choix du fournisseur (OVHcloud, Scaleway, AWS, Azure, GCP) sans un motif
  concret nouveau — cette ADR ferme la question du choix de principe, pas les détails
  d'implémentation listés ci-dessous.

## Ce que cette ADR ne fige pas (décisions de Phase 0 restantes)

Région OCI, forme de VM exacte (flexible ou fixe), nombre définitif de vCPU, quantité définitive
de RAM, Block Volume vs Object Storage pour chaque type de donnée, PostgreSQL managé ou
auto-hébergé sur la VM, Redis managé ou auto-hébergé sur la VM, choix Terraform / OCI CLI /
procédure manuelle, pattern instance permanente légère + worker temporaire puissant, mécanisme
exact de démarrage/arrêt, outil de monitoring — toutes listées comme décisions ouvertes dans
`docs/roadmap/DECISION_BACKLOG.md`.
