# Architecture cible

> Voir `docs/INDEX.md` pour la navigation. Ce document couvre les diagrammes C4 Contexte,
> Conteneurs et Composants. Le déploiement détaillé est dans
> [`DEPLOYMENT_ARCHITECTURE.md`](DEPLOYMENT_ARCHITECTURE.md), le cycle de vie des jobs dans
> [`COMPUTE_AND_JOBS.md`](COMPUTE_AND_JOBS.md), le flux de données dans
> [`DATA_ARCHITECTURE.md`](DATA_ARCHITECTURE.md). Décision structurante principale :
> [ADR 0005](../adr/0005-modular-monolith-with-separated-workers.md) (monolithe modulaire) ;
> isolation du module Options : [ADR 0011](../adr/0011-options-module-isolation.md).

## 1. Principes évalués (confrontés au dépôt réel, décisions formalisées en ADR)

| Principe proposé | Confronté au dépôt | Décision |
|---|---|---|
| Monolithe modulaire comme base | `engine.py`/`optimizer.py` déjà découplés de Streamlit ; `job_launcher.py` déjà une frontière process réelle | **Retenu** — ADR 0005 |
| Séparation interface / orchestration / moteur / données | Partiellement déjà là (job_launcher sépare UI et calcul pour l'optimisation ; pas pour le backtest simple) | **Retenu**, à étendre au backtest simple (voir `DECISION_BACKLOG.md`) |
| Streamlit jamais moteur d'exécution | Aujourd'hui le backtest simple s'exécute dans le thread Streamlit — violé pour ce cas précis | **Retenu comme cible**, écart actuel documenté, pas corrigé dans cette mission |
| File de travaux asynchrone | Absente aujourd'hui (queue en dur à 1 job) | **Retenu** — ADR 0005, technologie en `Decision pending` — ADR 0006 |
| Workers de calcul séparés | `ProcessPoolExecutor` déjà interne à un job, mais mono-machine | **Retenu**, extension multi-machines |
| Redis + RQ ou Celery | Aucun prototype existant | **Decision pending** — ADR 0006, benchmark requis |
| PostgreSQL pour les métadonnées | Aucune base aujourd'hui, catalogue JSON mort en production | **Retenu** — ADR 0007 |
| Données de marché en Parquet sur volume dédié | Parquet utilisé à un seul endroit aujourd'hui (EODHD normalisé) | **Retenu**, uniformisation — ADR 0008 |
| Conservation du job directory comme artefact portable | Contrat déjà stable, documenté, avec compatibilité descendante | **Retenu sans changement** |
| Conteneurisation Docker | Absente aujourd'hui | **Retenu** — ADR 0009 |
| Docker Compose pour la première version serveur | — | **Retenu** — ADR 0009 |
| Reverse proxy Caddy ou Nginx | Absent aujourd'hui | **Retenu**, choix technique en `DECISION_BACKLOG.md` |
| Environnements local/staging/production | Un seul environnement aujourd'hui | **Retenu** — ADR 0012 |
| Architecture provider-agnostic | Déjà vrai côté port `MarketDataSource`, pas encore côté IG (registre absent) | **Retenu**, à étendre |
| Compatibilité Linux | Meilleure que redouté (voir `CURRENT_STATE.md` §3) | **Confirmé faisable sans réécriture majeure** |
| Stockage brut immuable | Déjà vrai côté EODHD, absent côté CSV local | **Retenu**, extension — ADR 0008 |
| Snapshots de données, hashes de provenance | Existent mais non reliés au manifeste de backtest | **Retenu**, correction du branchement — ADR 0008 |
| Reprise après interruption | Mécanisme moteur dormant | **Retenu**, branchement à planifier — voir `COMPUTE_AND_JOBS.md` |
| Architecture événementielle déterministe pour le moteur | Le moteur actuel (bar-par-bar, `on_bar()`) est déjà déterministe par construction | **Confirmé déjà conforme**, aucun changement requis |
| Absence de dépendance directe du moteur envers Streamlit/EODHD/IG/chemin physique | Déjà vrai pour `engine.py`/`strategies/*` (aucun `import streamlit`) ; `path_resolver` isole les chemins | **Confirmé déjà conforme** |
| Sécurité par variables d'environnement ou coffre de secrets | Déjà en place pour EODHD/IG (clé API en env, jamais sur disque pour les tokens IG) | **Retenu**, étendu à PostgreSQL/Redis |
| IG démo et lecture seule uniquement, aucune fonction de trading live | Déjà vrai structurellement (aucune méthode d'écriture dans `IgClient`) | **Confirmé déjà conforme, à ne jamais régresser** |

Refus explicite de la multiplication de microservices : un serveur unique en Phase 1, des
frontières de module claires plutôt que des services réseau séparés pour chaque responsabilité.

## 2. Diagramme C4 — Contexte

```mermaid
C4Context
    title Backtest Nasdaq Revolution — Contexte système

    Person(user, "Utilisateur", "Développe et valide des stratégies de trading")

    System(app, "Plateforme de backtest", "Interface + orchestration + moteur + Data Center")

    System_Ext(eodhd, "EODHD", "Fournisseur de données de marché historiques (REST)")
    System_Ext(ig, "IG (démo)", "Courtier — lecture seule, prix et infos marché")
    System_Ext(github, "GitHub", "Code source, issues, CI/CD futur")
    System_Ext(compute, "Serveur de calcul", "Machine(s) Linux dédiée(s) à l'exécution")
    System_Ext(storage, "Stockage NVMe", "Données de marché et résultats, hors code")

    Rel(user, app, "Utilise via navigateur")
    Rel(app, eodhd, "Télécharge données historiques (HTTPS)")
    Rel(app, ig, "Interroge prix/marchés démo (HTTPS, lecture seule)")
    Rel(app, github, "Code versionné, déployé depuis")
    Rel(app, compute, "S'exécute sur")
    Rel(app, storage, "Lit/écrit données et résultats")
```

## 3. Diagramme C4 — Conteneurs

```mermaid
C4Container
    title Backtest Nasdaq Revolution — Conteneurs (cible Phase 1+)

    Person(user, "Utilisateur")

    System_Boundary(platform, "Plateforme de backtest") {
        Container(ui, "Interface Streamlit", "Python/Streamlit", "Affiche, configure, déclenche des jobs — jamais de calcul lourd")
        Container(orchestrator, "Service d'orchestration", "Python", "Reçoit les demandes de job, publie sur la file, expose le statut")
        Container(queue, "File Redis", "Redis + RQ/Celery (ADR 0006)", "File de travaux, découplage UI/calcul")
        Container(workers_bt, "Workers backtest", "Python (process)", "Exécutent des backtests unitaires")
        Container(workers_opt, "Workers optimisation", "Python (process, ProcessPoolExecutor interne)", "Exécutent des campagnes d'optimisation")
        ContainerDb(postgres, "PostgreSQL", "PostgreSQL", "Métadonnées : catalogue, index de jobs, registre IG, audit")
        ContainerDb(parquet, "Stockage Parquet", "Fichiers sur volume NVMe", "Données de marché normalisées/dérivées, brut immuable")
        ContainerDb(results, "Stockage résultats", "Fichiers sur volume NVMe", "Job directories (contrat préservé)")
        Container(proxy, "Reverse proxy", "Caddy ou Nginx", "HTTPS, routage")
        Container(backup, "Sauvegardes", "Job planifié", "PostgreSQL + fichiers critiques")
        Container(supervision, "Supervision", "Logs + métriques", "Observabilité (voir SECURITY_AND_OPERATIONS.md)")
    }

    System_Ext(eodhd, "EODHD")
    System_Ext(ig, "IG démo")

    Rel(user, proxy, "HTTPS")
    Rel(proxy, ui, "Route vers")
    Rel(ui, orchestrator, "Demande un job")
    Rel(orchestrator, queue, "Publie un travail")
    Rel(queue, workers_bt, "Distribue")
    Rel(queue, workers_opt, "Distribue")
    Rel(workers_bt, results, "Écrit job directory")
    Rel(workers_opt, results, "Écrit job directory")
    Rel(workers_opt, eodhd, "Télécharge si nécessaire")
    Rel(workers_opt, ig, "Interroge si nécessaire")
    Rel(orchestrator, postgres, "Lit/écrit métadonnées")
    Rel(ui, postgres, "Lit catalogue/index")
    Rel(workers_opt, parquet, "Lit données de marché")
    Rel(backup, postgres, "Sauvegarde")
    Rel(backup, results, "Sauvegarde sélective")
    Rel(supervision, workers_opt, "Collecte logs/métriques")
    Rel(supervision, workers_bt, "Collecte logs/métriques")
```

## 4. Diagramme de composants (vue interne)

```mermaid
flowchart TB
    subgraph UI["Interface (pages/ + components/)"]
        P1[Pages Streamlit]
        C1[Composants réutilisables]
    end

    subgraph SVC["Services applicatifs (services/)"]
        S1[Job orchestration service]
        S2[Strategy registry service]
        S3[Reporting service]
        S4[Audit service]
    end

    subgraph ENGINE["Moteur"]
        E1[Backtest engine — engine.py]
        E2[Optimization engine — optimizer.py]
        E3[Validation engine — Phase 3, nouveau]
    end

    subgraph MD["market_data/"]
        M1[Ports — MarketDataSource]
        M2[Provider adapters — CSV/EODHD/IG]
        M3[Resample + Calendar]
        M4[Quality + Provenance]
        M5[Catalog unifié]
    end

    subgraph STORE["Storage / Config"]
        D1[(PostgreSQL — métadonnées)]
        D2[(Parquet — données marché)]
        D3[(Job directories — résultats)]
        D4[Configuration / secrets]
    end

    P1 --> C1
    P1 --> S1
    P1 --> S2
    P1 --> S3
    S1 --> ENGINE
    S1 --> D1
    S1 --> D3
    S2 --> ENGINE
    ENGINE --> MD
    MD --> M1 --> M2
    M2 --> M3 --> M4
    M4 --> M5
    M5 --> D1
    M2 --> D2
    S3 --> D3
    S4 --> D1
    ENGINE -.->|"aucune dépendance directe"| P1
```

Principe clé (confirmé déjà respecté par le code actuel, voir §1) : le moteur (`ENGINE`) ne
dépend jamais de l'UI, de Streamlit, ni d'un fournisseur de données précis — seulement du port
`MarketDataSource`.

## 5. Compatibilité garantie avec l'existant

Cette architecture cible ne casse aucun des éléments suivants (contrainte explicite) :
chargement CSV historique, contrat des job directories, `progress.json`, `config_used.json`,
`results.csv`, `best_strategies.csv`, `metrics.json`, `report.html`, `archive.zip`, stratégies et
résultats déjà existants, fonctionnement local (sans serveur), Data Center, connecteurs EODHD/IG
démo, manifestes reproductibles (une fois corrigés — ADR 0008), tests existants.
