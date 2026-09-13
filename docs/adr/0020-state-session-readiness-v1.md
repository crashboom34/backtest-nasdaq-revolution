# State/Session Readiness V1 : alignement de frontière strategy-aware pour l'état informational

Status: Accepté

**Contexte** : la correction TRAIN/TEST exacte (ADR 0018) et le WARMUP dynamique (ADR 0019)
garantissent des frontières temporelles exactes et des indicateurs correctement convergés — mais
aucun des deux ne rejoue `on_bar()` avant `loop_start`. Perfect Revolution construit son Opening
Range (`_or_high`/`_or_low`/`_or_ready`, fenêtre `or_start_h:m`→`or_end_h:m`) exclusivement dans
`on_bar()`. Une frontière TRAIN/TEST exacte peut désormais tomber n'importe où dans la journée,
y compris pendant ou après cette fenêtre — prouvé empiriquement (audit précédent) : `_or_ready`
reste `False` toute la journée, ou l'Opening Range calculé est silencieusement faux.

**Classification centrale (réduit fortement le périmètre)** : état INFORMATIONAL (Opening Range —
dérivé uniquement des prix, reconstructible depuis les données) vs état EXECUTION (compteurs de
trades, PnL journalier, système on/off — dépendant de CE backtest précis, jamais reconstructible
sans rompre l'indépendance scientifique TRAIN/TEST). L'état EXECUTION est déjà correctement traité
(reset automatique sur nouvelle journée + instance `Strategy()` fraîche par backtest, aucune fuite
TRAIN→TEST). Cette mission ne traite QUE l'état INFORMATIONAL.

## Décision 1 — Architecture READY-3 : déclaration stratégie + résolution protocole

`Strategy.state_readiness(params) -> DailyStateReadiness` (staticmethod, mirroring exact de
`required_warmup(params)`) déclare une contrainte minimale ; `optimizer.py::Optimizer.run()`
(juste après `compute_split_dates()`, jamais dedans) résout la frontière effective via
`strategy_contracts.resolve_state_ready_boundary()` (fonction pure). `engine.py` reste totalement
ignorant de cette notion — aucune modification.

**Options écartées** (deletion test — si Perfect Revolution disparaît, l'architecture reste-t-elle
utile pour une future stratégie stateless/weekly/24-7 ?) : moteur seul (`engine.py` n'a même pas
la visibilité géométrique nécessaire) ; hook stratégie seul (orchestrerait un protocole qu'elle ne
connaît pas) ; protocole seul (dupliquerait la connaissance stratégie-spécifique entre futurs
protocoles TRAIN/TEST et Walk-Forward).

## Décision 2 — Règle V1 volontairement simple, aucun calendrier, aucun replay

`requested_boundary` convertie en heure locale (fuseau déclaré) ; `<= latest_safe_start_hour:minute`
(inclusif) → inchangée ; sinon → minuit local du jour calendaire **suivant**, construction
DST-safe (date locale + 1 jour, puis relocalisation via `pd.Timestamp(date, tz=)` — jamais
`+ Timedelta(hours=24)`, vérifié empiriquement décalé d'1h les jours de changement d'heure).
Aucune notion de "jour de marché" : une frontière tombant un week-end est acceptée telle quelle,
le moteur démarre à la première barre réellement disponible — aucune donnée perdue. La qualité/
complétude réelle des données (trous, jours fériés) reste explicitement hors scope (Data
Center/data quality), volontairement non traitée ici pour éviter un pseudo-calendrier prématuré.

**Replay `on_bar()` rejeté** : `on_bar()` n'est pas une fonction pure de reconstruction — un
replay sans exécution muterait quand même les compteurs de façon incohérente, un replay avec
exécution fictive contaminerait l'indépendance TEST.

## Décision 3 — `requested_boundary`/`effective_boundary` conservés distincts, jamais l'un n'écrase l'autre

`StateReadinessResolution(requested_boundary, effective_boundary, adjusted)`. TRAIN/TEST restent
contigus sur la MÊME frontière effective (`TRAIN=[train_start,effective_boundary)`,
`TEST=[effective_boundary,test_end]`) — aucune barre perdue ni dupliquée (invariant Dette B
préservé). Validation stricte `train_start < effective_boundary < test_end` : `NoStateReadyBoundary`
explicite sinon, jamais une fenêtre TEST vide ou un repli silencieux.

## Décision 4 — Versioning séparé de `TRAIN_TEST_SEMANTICS_VERSION`

`STATE_READINESS_SEMANTICS_VERSION = "daily-state-ready-v1"`, indépendante d'`exact-boundary-v2`
(inchangée) : deux contrats scientifiques distincts (géométrie temporelle vs ajustement
strategy-aware). `validate_resume_state_readiness_semantics()` (mirroring exact de
`validate_resume_train_test_semantics()`) refuse la reprise si le job source n'a pas la même
politique de readiness (absente = legacy) — jamais bloquante pour une stratégie stateless ou un
run sans train/test.

## Décision 5 — Persistance additive

`config_used.json` gagne `state_readiness_semantics_version` (None si non readiness-aware).
`meta.json`'s `train_test_windows` gagne `requested_boundary`/`adjusted` à côté de `boundary`
(qui reste la frontière EFFECTIVE) — jamais un champ existant écrasé, anciens `meta.json` restent
lisibles tels quels.

## Conséquences

- **Changement scientifique attendu, pas systématique** : seul le split ratio (frontière à un
  instant quelconque) est réellement exposé ; la méthode date (D1, minuit local) reste presque
  toujours déjà admissible (`00:00 <= or_start`) — aucun changement attendu pour ce cas.
- `compute_split_dates()`, `engine.py`, `opt_start_date`, `max_rows`, `params_hash` restent
  strictement inchangés.
- **Hors scope explicite, différé** : qualité/complétude réelle des données (Data Center),
  généralisation à des stratégies non-daily (weekly, 24/7) — le contrat `DailyStateReadiness`
  couvre seulement le cas daily-stateful ; une future stratégie à une autre granularité
  nécessitera sa propre déclaration, sans modification du protocole de résolution.
- **Duplication mineure acceptée** : `_load_strategy()` est appelé une fois de plus dans
  `Optimizer.run()` (pour interroger `state_readiness()`) qu'il ne l'était déjà dans
  `optimizer_process.py` — coût I/O négligeable, non optimisé pour cette V1 (revue de code).
