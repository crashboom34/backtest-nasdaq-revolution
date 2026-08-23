# Identité de snapshot et fuseau horaire du premier dataset IG démo (AF-V-01)

Status: Accepté — **fuseau horaire confirmé le 2026-08-23** (voir "Correction 2026-08-23"
ci-dessous ; la Décision 2 initiale reposait sur une simple déduction depuis l'heure observée,
explicitement proscrite par la mission de revue AF-V-01 "Timezone Safety Gate" — corrigée avec
une preuve vérifiable, pas seulement renforcée).

**Contexte** : AF-V-01 Phase A a acquis le premier `DatasetSplitPlan` basé sur des données IG
(broker externe, epic `IX.D.NASDAQ.IFD.IP`, résolution `MINUTE_3`), distinct du dataset MT5 local
existant (`nasdaq_3m.csv`). Deux décisions étaient nécessaires pour référencer ce dataset avec les
contrats existants (`ResearchRun.dataset_snapshot_id`, `DatasetSplitPlan.dataset_snapshot_id`,
`SplitBoundary.start`/`.end`), sans modifier aucun code (ces champs sont déjà des `str` libres,
aucun parsing/validation de préfixe n'existe nulle part dans le code actuel).

**Décision 1 — identité `dataset_snapshot_id`** : `"ig_demo:sha256:<hash>"`, où `<hash>` est le
SHA-256 du fichier RAW JSON exact tel que reçu de l'API IG (jamais d'une version normalisée) —
même famille de forme que la convention AF-DATA existante `"local_csv:sha256:<hash>"`
(`<provider>:sha256:<hash>`, identité par contenu). Aucune modification de code : ce champ est un
`str` libre partout où il est consommé. L'epic/la résolution ne sont pas encodés dans l'identifiant
lui-même — ils font partie du contenu haché (l'enveloppe RAW les inclut), donc deux acquisitions
IG différentes (epic ou résolution différents) produisent mécaniquement des hash différents, même
principe que `"local_csv:..."` qui n'encode pas non plus le nom du CSV source dans l'identifiant.

**Décision 2 — hypothèse de fuseau horaire** : l'API IG (`GET /prices/{epic}`, VERSION 3) renvoie
`snapshotTime` sans indicateur de décalage (`"yyyy/MM/dd HH:mm:ss"`, tz-naive). Aucune
documentation officielle consultée ne confirme explicitement le fuseau. Preuve empirique
disponible (AF-V-01, 2026-08-17) : comparaison entre l'horodatage UTC système au moment d'un appel
(`2026-08-17T16:36:10+00:00`) et le dernier `snapshotTime` reçu dans le même appel
(`2026/08/17 18:33:00`) — écart ≈ +2h, cohérent avec CEST (Europe/Paris, heure d'été, août).
**Retenu comme hypothèse de travail** : `snapshotTime` IG est traité comme `+02:00`, cohérent avec
la convention `"time_paris"` déjà utilisée par `engine.py` pour le CSV MT5 local (voir
`dataset_split.py::SplitBoundary`, note sur `engine.py:89-90`) — pas une coïncidence favorable
confirmée, une hypothèse empirique non validée par une source officielle IG.

**Conséquence** : les bornes du `DatasetSplitPlan` IG (`TRAIN`/`FINAL_HOLDOUT`) sont exprimées avec
l'offset `+02:00` sur la foi de cette hypothèse. Si une source officielle infirme cette hypothèse
plus tard, les bornes calendaires du split devront être recalculées (translation simple de
l'offset, pas une réacquisition de données) avant toute exécution de `FINAL_HOLDOUT` — documenté
ici pour qu'une future correction ne soit jamais silencieuse.

## Considered Options

- Traiter `snapshotTime` comme UTC par défaut (comme le fait déjà, de façon non vérifiée non plus,
  `data_manifest.json` pour le CSV MT5 local) — écarté : l'écart empirique mesuré (~2h) contredit
  directement cette hypothèse pour IG spécifiquement.
- Laisser le fuseau non résolu et refuser de construire un `SplitBoundary` — écarté : bloquerait
  toute la Phase A pour une incertitude de 2h sur un dataset dont aucune zone n'est encore exécutée
  (`TRAIN` ne l'est jamais dans cette mission, `FINAL_HOLDOUT` est hors scope avant `AF-V-02`) ;
  disproportionné, l'hypothèse documentée suffit à ce stade.

## Correction 2026-08-23 — fuseau confirmé, pas seulement déduit d'une heure observée

Une revue dédiée ("AF-V-01 Timezone Safety Gate") a interdit explicitement de se contenter d'une
déduction depuis une seule heure observée (la méthode utilisée ci-dessus en Décision 2 initiale).
Preuve de remplacement, vérifiable et non ponctuelle :

- **Le fichier RAW déjà acquis contient, pour CHACUN de ses 4800 enregistrements, un second champ
  `snapshotTimeUTC`** (`"2026-08-03T14:45:00"`, format `%Y-%m-%dT%H:%M:%S`, sans indicateur
  d'offset explicite mais nommément UTC), en plus de `snapshotTime` (`"2026/08/03 16:45:00"`,
  format `%Y/%m/%d %H:%M:%S`) — les deux champs sont retournés par l'endpoint `GET /prices/{epic}`
  VERSION 3 réel, confirmé en relisant le fichier RAW lui-même, pas une supposition.
- **Vérification exhaustive sur les 4800 enregistrements** (pas seulement le premier/dernier) :
  `snapshotTime - snapshotTimeUTC == exactement 2h00, sans une seule exception`, du
  2026-08-03T16:45:00 au 2026-08-17T18:39:00 — confirme que l'hypothèse `+02:00` de la Décision 2
  était correcte, mais la démontre maintenant par recoupement avec le propre champ UTC du
  fournisseur plutôt que par une comparaison d'horloge système.
- **Corroboration externe indépendante** (recherche web ciblée, documentation officielle IG Labs
  inaccessible directement — HTTP 403, comme déjà rencontré et documenté le 2026-08-06 dans
  `AI_HANDOFF.md`) : un fil officiel IG Labs intitulé *"prices API timezone is messy"* confirme que
  `snapshotTime` est une source connue de confusion, tandis que `snapshotTimeUTC` existe justement
  pour lever cette ambiguïté ; la bibliothèque de référence déjà utilisée dans ce projet
  (`trading-ig`, voir `AI_HANDOFF.md` 2026-08-06) utilise explicitement `snapshotTimeUTC` comme
  champ d'indexation pour les réponses VERSION 3 et **abandonne délibérément** `snapshotTime` pour
  cette même raison.
- **Limite résiduelle assumée, non résolue ici** : la fenêtre acquise (3–17 août 2026) ne traverse
  aucune transition DST (Europe/Paris CEST→CET fin octobre) — l'écart constant de 2h est donc
  valide pour CETTE fenêtre précise uniquement ; rien ne prouve encore le comportement de
  `snapshotTime` autour d'une transition DST. Sans conséquence sur les données déjà acquises (aucune
  transition dans leur période), mais à revérifier avant toute future acquisition IG qui en
  traverserait une.

**Découverte corollaire, non un simple raffinement — un gap de code réel** : `market_data/ig/
normalize.py::normalize_price_records()` lit exclusivement `record["snapshotTime"]` (champ
ambigu) et **n'utilise jamais `record["snapshotTimeUTC"]`** (champ non ambigu), alors que ce
dernier est bien présent dans chaque réponse réelle. La colonne `time` produite par ce module —
et donc `results/datasets/ig_ix_d_nasdaq_ifd_ip_minute_3/normalized/ig_prices_normalized.csv`,
déjà produit par `AF-V-01` Phase A — porte en réalité la valeur `snapshotTime` (heure locale
+02:00 pour cette fenêtre), **pas** une valeur UTC, malgré le docstring du module qui affirme
"`time` tz-naive UTC — même convention que `market_data.eodhd.normalize`". Cette affirmation est
**vraie pour EODHD** (`market_data/eodhd/normalize.py` convertit explicitement via
`pd.to_datetime(..., utc=True).dt.tz_localize(None)`, ou via le champ `timestamp` Unix
explicitement UTC pour l'intraday) mais **fausse pour IG en l'état actuel du code**.

**Conséquence concrète, vérifiée numériquement** : si ce CSV était chargé tel quel via
`engine.py::_add_market_time_columns()` (`df["time"].dt.tz_localize("UTC").dt.tz_convert(PARIS)` —
qui suppose que `df["time"]` est déjà en UTC), la colonne dérivée `time_paris` serait décalée de
**+2h supplémentaires** par rapport à l'heure de Paris réelle (vérifié : bougie
`snapshotTime="2026-08-03 16:45:00"` → `time_paris` calculée = `18:45:00+02:00`, alors que l'heure
de Paris réelle pour cet instant, dérivée de `snapshotTimeUTC`, est `16:45:00+02:00` — coïncidence
trompeuse : la valeur brute de `snapshotTime` ressemble numériquement à l'heure de Paris réelle
pour cette fenêtre estivale, ce qui masquerait l'erreur à une lecture rapide). Toute
exécution future de `run_backtest(start_date=, end_date=)` sur ce CSV comparerait donc les bornes
`SplitBoundary` (elles, correctement ancrées sur l'UTC réel — voir ci-dessus) à une colonne
`time_paris` dérivée d'une valeur non-UTC, avec un décalage systématique de 2h.

**Non corrigé dans cette revue d'investigation, intentionnellement** : elle interdisait
explicitement toute modification de code, toute création de `HoldoutAccessEvent`, et tout
démarrage d'`AF-V-02`. **Bonne nouvelle pratique** : le fichier RAW déjà acquis contient déjà
`snapshotTimeUTC` pour chaque bougie — corriger et re-normaliser ne nécessitera aucune
ré-acquisition réseau (donc aucune exposition supplémentaire du holdout).

## Contrat de correction (2026-08-23, `/domain-modeling` puis `/tdd`)

Une mission de suivi dédiée ("IG Timezone Normalization Fix") a demandé la correction elle-même,
avec la contrainte explicite de **ne jamais utiliser un offset fixe** (+1h/+2h/-1h interdits) —
seule une lecture directe du champ `snapshotTimeUTC` est acceptable. Contrat retenu :

1. **`snapshotTimeUTC` devient un champ obligatoire** de `_REQUIRED_FIELDS` dans
   `normalize_price_records()` — lève `IgResponseError` si absent (même pattern défensif déjà en
   place pour les champs OHLC manquants). `snapshotTime` devient un champ non requis, non consommé
   pour construire `time` (il reste dans l'enregistrement brut IG, simplement ignoré par ce
   module).
2. **`snapshotTime` n'est PAS conservé comme colonne auxiliaire** dans le DataFrame produit
   (contrairement aux colonnes `*_bid`/`*_ask`, gardées parce qu'elles portent une information de
   prix distincte sans équivalent canonique). `snapshotTime` ne porte aucune information
   supplémentaire par rapport à `snapshotTimeUTC` — ce n'est pas une donnée différente, c'est une
   représentation redondante et ambiguë du même instant. La conserver réintroduirait exactement
   l'ambiguïté que ce correctif élimine, pour aucun bénéfice réel : décision volontaire de ne PAS
   étendre le schéma au-delà du correctif demandé.
3. **Parsing** : `pd.to_datetime(record["snapshotTimeUTC"], format="%Y-%m-%dT%H:%M:%S", utc=True)`
   puis `.tz_localize(None)` — même idiome exact que `market_data/eodhd/normalize.py`
   (`pd.to_datetime(..., utc=True).dt.tz_localize(None)`), pas un simple parse naïf sans `utc=True`.
   Numériquement un no-op ici (la chaîne ne porte aucun offset à convertir), mais defense-in-depth
   cohérente avec la convention déjà établie : si une future version de l'API IG ajoutait un
   indicateur d'offset explicite à `snapshotTimeUTC`, `utc=True` le convertirait correctement au
   lieu de l'ignorer silencieusement.
4. **Docstring corrigé** pour documenter la vraie source (`snapshotTimeUTC`, pas `snapshotTime`) et
   renvoyer vers cet ADR pour le contexte de la découverte. Colonnes `*_bid`/`*_ask`/`open`/`high`/
   `low`/`close`/`volume` **inchangées** — dérivées des champs de prix IG, indépendantes du choix de
   champ temporel.

Aucune nouvelle table/schéma, aucun nouveau module — correctif ciblé sur la seule source temporelle
de `normalize_price_records()`.

## Note de clôture (2026-08-23) — première exécution réelle et limite méthodologique révélée

La première (et unique) exécution de `NASDAQ Perfect Revolution V1.1` + `DEFAULT_PARAMS` sur ce
`FINAL_HOLDOUT` (`validation_run_id="af-v01-ig-demo-final-holdout-oos"`) a produit `n_trades=0`.
Vérifié : aucun bug de filtrage (2400 bougies réelles dans la fenêtre, 5 jours ouvrés présents),
résultat honnête de la sélectivité de la stratégie sur un échantillon court.

**Limite méthodologique trouvée en revue de clôture (`code-review`, axe "Scientific correctness"),
non corrigée, documentée pour toute lecture future de cette `ValidationRun`** : `engine.run_backtest()`
filtre le DataFrame sur la seule fenêtre `FINAL_HOLDOUT` **avant** d'appeler `strategy.prepare()`
(`engine.py:87-98`) — les indicateurs (`ema_trend_len=120`, `atr_len=14`, calculés par `.ewm()`)
ne disposent donc que des bougies du holdout lui-même, jamais de celles de `TRAIN` qui le précèdent
immédiatement. Avec `WARMUP=130` bougies M3 (~6h30) seulement ignorées avant le début des trades
possibles (`engine.py:137`), la convergence de l'EMA(120) reste partielle sur ce court début de
fenêtre — un biais de "cold start" plausible, distinct du fuseau horaire, qui peut avoir
partiellement contribué au résultat `n_trades=0`, sans qu'on puisse trancher avec certitude par
seule lecture statique (nécessiterait une instrumentation du run, non autorisée : aurait constitué
un second run). **Non corrigé ici** : ce n'est pas un défaut introduit par `AF-V-01` — c'est une
caractéristique déjà partagée par le split train/test existant de l'optimiseur
(`optimizer.py::TrainTestConfig`), jamais questionnée avant ce point ; la corriger toucherait
`engine.py` lui-même, hors du périmètre strictement temporel de ce ticket, et nécessiterait son
propre `/domain-modeling` + `/tdd`.
