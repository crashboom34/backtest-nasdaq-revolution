# Plan de benchmark et dimensionnement serveur

> Voir `docs/INDEX.md` pour la navigation. **Aucun benchmark n'est exécuté dans cette mission** —
> protocole et repères de marché seulement. Prix vérifiés via `WebSearch`/`WebFetch` le
> **2026-08-06** ; à revérifier au moment de la commande (marché volatile, voir §3). Cible
> principale : **Oracle Cloud Infrastructure Pay As You Go** —
> [ADR 0015](../adr/0015-oracle-cloud-infrastructure-payg.md). Hetzner reste une alternative
> conditionnelle documentée en §3 ; OVHcloud/Scaleway restent documentés mais non prioritaires.

## 1. Protocole de benchmark (à exécuter en Phase 0/1, pas ici)

### Scénarios de données

| Taille | Bougies | Objectif |
|---|---|---|
| Petit | 20 000 | Temps de réponse interactif |
| Moyen | 200 000 | Cas d'usage courant |
| Grand | 1 000 000 | Cas limite, historique long |

### Scénarios de combinaisons

12, 100, 1 000 combinaisons — croisés avec 1, 2, 4, 8 workers.

### Mesures à collecter pour chaque cellule (taille × combinaisons × workers)

- Temps total, temps moyen par combinaison.
- CPU (moyenne, pic), RAM (moyenne, pic), lecture/écriture disque.
- Taille des résultats produits.
- Temps de chargement initial des données (CSV/Parquet).
- Surcharge de la file de jobs (latence d'attribution d'un travail à un worker).

### Critères de sélection du serveur

1. Le profil "recommandé" doit traiter le scénario "moyen × 100 combinaisons × 4 workers" dans un
   temps jugé acceptable par l'utilisateur (seuil à définir au moment du benchmark, pas ici).
2. Le profil ne doit pas saturer la RAM sur le scénario "grand × 1000 combinaisons × 8 workers"
   (marge de sécurité recommandée : 30 %).
3. Le coût mensuel est comparé au débit mesuré (combinaisons/seconde par euro), pas seulement au
   prix affiché.

## 2. Trois profils techniques (structure — à instancier après benchmark)

| Profil | vCPU | RAM | Stockage | Usage | Critère de montée/descente en gamme |
|---|---|---|---|---|---|
| **Minimal** | 4-8 | 16-32 Go | Block Volume dimensionné au besoin | Staging et petits backtests | Tout scénario "moyen" met > 2× le temps local |
| **Recommandé** | 8-16 | 32-64 Go | Idem, dimensionné après benchmark | Optimisations intermédiaires | Le scénario "grand × 1000 × 4" sature CPU/RAM en continu |
| **Intensif temporaire** | Supérieur au recommandé, formes flexibles OCI (jusqu'à 126 OCPU sur `E5.Flex`) | Proportionnelle | Idem | Activé uniquement pour une grosse campagne, **arrêt immédiat après** | Jamais laissé actif par défaut — voir contrôle des coûts, `SECURITY_AND_OPERATIONS.md` §7 |

Sur OCI, les formes flexibles (`VM.Standard.E4.Flex`/`E5.Flex`) permettent de dimensionner OCPU
et RAM indépendamment sans changer de gamme — les trois profils ci-dessus sont donc des points de
curseur sur une même forme, pas trois machines différentes à choisir a priori.

## 3. Repères de marché (Fait vérifié, 2026-08-06 — à revérifier avant commande)

### Oracle Cloud Infrastructure — cible principale ([ADR 0015](../adr/0015-oracle-cloud-infrastructure-payg.md))

**Fait vérifié via documentation officielle** (`docs.oracle.com`, fetch direct le 2026-08-06) :

| Forme | OCPU | RAM max | Processeur | Notes |
|---|---|---|---|---|
| `VM.Standard.E4.Flex` | 1-64 | jusqu'à 1024 Go (64 Go/OCPU) | AMD EPYC 7J13 | AMD, génération précédente |
| `VM.Standard.E5.Flex` | 1-126 | jusqu'à 1049 Go | AMD EPYC 9J14 | AMD, génération courante — posture recommandée, voir §5 |
| `VM.Standard.E6.Flex` | 1-126 | jusqu'à 1454 Go | AMD EPYC 9J45 | AMD, génération la plus récente |
| `VM.Standard.A1.Flex` | 1-76 | jusqu'à 472 Go | Ampere Altra (ARM) | Palier Always Free disponible dessus — voir §5 pour la posture ARM |

Source : [OCI Compute Shapes](https://docs.oracle.com/en-us/iaas/Content/Compute/References/computeshapes.htm).

**Palier Always Free réel et permanent** (Fait vérifié, `docs.oracle.com`, fetch direct) :
jusqu'à 4 OCPU + 24 Go de RAM en Ampere A1 (1 500 heures-OCPU + 9 000 heures-Go/mois — équivalent
2 OCPU + 12 Go en continu, ou davantage en usage intermittent), 200 Go de Block Volume, 10-20 Go
d'Object Storage — jamais expire, disponible même après un essai payant. Source :
[Always Free Resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).
Utilisable pour héberger l'interface/orchestrateur du staging à coût nul pendant la Phase 0-1.

**Tarification Pay As You Go** — **Question ouverte / à reconfirmer** : des figures par
OCPU-heure et Go-heure ont été obtenues par recherche (env. 0,025-0,030 $/OCPU-heure et
0,0015-0,002 $/Go-heure de RAM selon la forme, citant `oracle.com/cloud/compute/pricing` et
`blogs.oracle.com` comme sources), mais la page officielle de tarification
(`oracle.com/cloud/price-list/`, `oracle.com/cloud/compute/pricing/`) a renvoyé une erreur HTTP
403 (protection anti-robot) lors de la tentative de vérification directe — même situation
rencontrée avec `labs.ig.com` plus tôt dans ce projet. **Ces chiffres ne doivent pas être traités
comme un tarif garanti** — à reconfirmer manuellement sur `oracle.com/cloud/price-list/` avant
tout engagement financier réel (voir aussi le contrôle des coûts, `SECURITY_AND_OPERATIONS.md` §7,
qui exige une estimation de coût avant toute campagne, indépendamment de ce document).

Stockage OCI (Fait vérifié via recherche, mêmes réserves de vérification directe que ci-dessus) :
Block Volume et Object Storage Standard de l'ordre de 0,0255 $/Go/mois — à reconfirmer.

### Hetzner — alternative conditionnelle (voir ADR 0015)

À réévaluer seulement si l'usage OCI mesuré devient intensif et permanent (critère de
réévaluation de l'ADR 0015 — voir la tendance générale du marché des serveurs dédiés en fin de
cette section, qui renforce cette réserve) :

| Offre repère | CPU | RAM | NVMe | Prix constaté (2026-08-06) | Comparaison au profil "recommandé" OCI |
|---|---|---|---|---|---|
| Hetzner AX52 (Ryzen 7 7700) | 8 cœurs / 16 threads (à reconfirmer sur le configurateur) | à reconfirmer (généralement 64-128 Go DDR5 ECC sur cette gamme) | à reconfirmer (généralement 2×512 Go-2 To NVMe) | 64 €/mois | Facturé au mois quel que soit l'usage — pertinent seulement si l'usage OCI mesuré devient quasi permanent (critère de réévaluation, ADR 0015) |
| Hetzner AX102 (Ryzen 9 7950X3D) | 16 cœurs / 32 threads | à reconfirmer | à reconfirmer | 259 €/mois | Palier "intensif" en usage permanent uniquement |

**Fait vérifié vs Hypothèse** : les prix et gammes ci-dessus sont des faits vérifiés à la date de
recherche, mais les specs RAM/NVMe exactes de l'AX52 n'ont **pas** pu être confirmées par la
requête (page produit sans détail exploitable au moment du fetch) — à traiter comme **Question
ouverte** jusqu'à vérification directe sur le configurateur Hetzner avant toute réévaluation.

Source : [Hetzner AX102](https://www.hetzner.com/dedicated-rootserver/ax102/) (consultée le
2026-08-06).

### OVHcloud et Scaleway — repères non prioritaires (documentés, plus la cible principale)

| Fournisseur | Offre repère | CPU | RAM | NVMe | Prix constaté (2026-08-06) |
|---|---|---|---|---|---|
| OVHcloud | Advance-2 2026 | AMD EPYC 4345P, 8 cœurs / 16 threads | 64-256 Go | 2×960 Go à 2×15,36 To | à partir de 173 $/mois |
| Scaleway Dedibox | Gamme AMD Ryzen | Variable (ex. Ryzen 5 PRO 3600 sur un exemple constaté) | Ex. 32 Go sur la config constatée | Ex. 2 To sur la config constatée | à partir de 33,99 €/mois **avec engagement 36 mois** |

Sources : [OVHcloud Bare Metal — Prices](https://us.ovhcloud.com/bare-metal/prices/),
[Scaleway Dedibox — AMD Ryzen dedicated servers](https://www.scaleway.com/en/amd-ryzen-dedicated-server/)
(consultées le 2026-08-06).

**Tendance générale du marché des serveurs dédiés (Fait vérifié)** : le coût de fabrication
devrait augmenter de 15 à 35 % entre fin 2025 et fin 2026 (demande RAM/NVMe tirée par l'IA) ;
OVHcloud a annoncé des hausses moyennes de 9 à 11 % sur les nouvelles instances déployées entre
2026 et 2028 ([Le Monde Informatique](https://www.lemondeinformatique.fr/actualites/lire-les-prix-des-instances-flambent%C2%A0chez-ovh%C2%A0-99440.html))
— renforce l'intérêt d'un modèle PAYG (coût aligné sur l'usage) plutôt qu'un engagement long sur
un serveur dédié tant que l'intensité d'usage réelle n'est pas mesurée.

## 4. Recommandation de posture (Proposition, cohérente avec ADR 0015)

Démarrer sur **Oracle Cloud Infrastructure PAYG**, palier Always Free pour le staging léger, puis
formes flexibles payantes pour les workers de calcul à la demande. Réévaluer Hetzner uniquement
si le journal d'usage (voir `SECURITY_AND_OPERATIONS.md` §7) montre un usage intensif et
permanent sur plusieurs semaines. Ne pas rouvrir la comparaison OVHcloud/Scaleway sans motif
concret nouveau.

## 5. Posture x86 AMD vs ARM Ampere

**Démarrer sur x86 AMD** (`VM.Standard.E5.Flex` recommandé — génération courante, voir §3).
**ARM Ampere ne peut être retenu qu'après** : (a) un audit complet des dépendances Python du
projet pour confirmer la disponibilité de binaires ARM (`numpy`, `pandas`, `numba`, `pandas-ta`,
`scipy`, `pyarrow` — voir `requirements-server.txt`) sans recompilation fragile, et (b) un
benchmark comparatif direct AMD vs Ampere sur le protocole du §1. Le palier Always Free
(Ampere A1) reste utilisable pour l'interface/orchestrateur (charge légère, pas de calcul
intensif) sans attendre cet audit — seule l'utilisation d'Ampere pour les **workers de calcul**
est conditionnée à l'audit et au benchmark.
