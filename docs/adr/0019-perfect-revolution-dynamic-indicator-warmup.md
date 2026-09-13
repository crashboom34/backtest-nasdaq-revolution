# Warmup dynamique des indicateurs pour Perfect Revolution : `required_warmup(params)`

Status: Accepté

**Contexte** : `WARMUP=130` (constante fixe) déterminait depuis combien de barres `on_bar()`
pouvait commencer à décider, indépendamment des paramètres réels du run. Mathématiquement
insuffisant dès que le contexte réel disponible avant `start_date` est court (ex. optimisation
sans `opt_start_date`, ou TRAIN d'un split train/test démarrant au tout début du dataset) :
l'influence résiduelle de la condition initiale d'un `ewm(adjust=False)` après k barres vaut
`(1-alpha)^k` — à k=130, elle atteint encore ~11,5 % pour `ema_trend_len=120` (DEFAULT_PARAMS) et
~59,5 % pour `ema_trend_len=500` (max `PARAM_SCHEMA`), jamais négligeable. Corrobore une
suspicion déjà documentée dans `docs/adr/0017-*.md` (biais de cold-start plausible sur
l'exécution réelle AF-V-01 FINAL_HOLDOUT), quantifiée ici pour la première fois (audit read-only
préalable).

## Décision 1 — `Strategy.required_warmup(params) -> int`, pas une constante moteur

Le moteur (`engine.py`) reste totalement ignorant d'EMA/ATR/tolérance de convergence — toute la
complexité mathématique reste encapsulée dans la stratégie, seule à connaître ses propres
indicateurs. Dispatch : `required_warmup()` présent → utilisé ; sinon `WARMUP` de classe → utilisé
(comportement historique) ; sinon `130` (défaut historique) — rétrocompatibilité totale,
aucune stratégie existante cassée.

**Options écartées** : `warmup = max(ema_trend_len, ema_filter_len, atr_len)` (rejeté —
mathématiquement faux, un span de N barres ne donne pas N barres de convergence réelle) ; un
multiplicateur fixe `C × N` sans ancrage explicite sur une tolérance (rejeté — arbitraire ; une
fois ancré sur un epsilon, un tel multiplicateur devient de toute façon équivalent au calcul
explicite ci-dessous, en moins lisible et moins auditable).

## Décision 2 — tolérance de convergence explicite `WARMUP_EPSILON = 0.01`

Politique scientifique explicite, documentée dans le code : l'influence résiduelle de
l'initialisation doit être `<= 1 %` pour chaque indicateur consulté à la première décision.
**Ce n'est pas** une garantie d'erreur de prix absolue ni un signal identique à un historique
infini — une politique de convergence reproductible et auditable. Formule :
`k = ceil(log(epsilon) / log(1-alpha))`, `alpha=2/(span+1)` pour les EMA (`ema_trend`/
`ema_filter`), `alpha=1/atr_len` pour l'ATR (RMA de Wilder).

## Décision 3 — lookback `ema_trend[i-5]` pris en compte (`+5` barres)

`on_bar()` consulte `ema_trend[i-5]` en plus de `ema_trend[i]` (`trend_long`/`trend_short`) — la
barre `i-5` doit elle-même avoir convergé, d'où `k_ema_trend + 5`. Seul ce lookback, réellement
utilisé aujourd'hui, est pris en compte — pas de généralisation spéculative à d'autres décalages
non consultés par cette stratégie.

## Décision 4 — validation stricte, indépendante de `PARAM_SCHEMA`

`ema_trend_len`/`ema_filter_len`/`atr_len` doivent être des nombres strictement positifs
(`ValueError` explicite sinon, y compris pour `None`/chaîne/`bool`, trouvés en revue) — jamais
dépendant des maxima UI, qu'une config externe (job JSON direct) peut légitimement dépasser tant
qu'elle reste mathématiquement valide.

## Décision 5 — pas de nouveau versioning au niveau job

`required_warmup(params)` est déterministe à partir de `params` + code/version de la stratégie,
déjà tracés par `git_commit` (`data_manifest.json`). Introduire un champ dédié serait par ailleurs
trompeur dans l'Optimizer : le warmup peut différer PAR combinaison de paramètres au sein d'un
même run — un seul `required_warmup_bars` au niveau run ne serait pas représentatif.

## Conséquences

- **Changement scientifique attendu, pas systématique** : le warmup DEFAULT passe de 130 à 282
  barres — un backtest démarrant très près du début du dataset PEUT produire un résultat
  différent. **Vérifié empiriquement non affecté** pour la référence historique GATE DATA (114
  trades / `net_ret_pct=-1.07580480000006`, `nasdaq_3m.csv` complet, `DEFAULT_PARAMS`) — aucune
  barre supplémentaire ignorée (130→282, sur un dataset de plusieurs années) n'a modifié le
  résultat.
- **Hors scope explicite** : la readiness d'état path-dependent de Perfect Revolution (opening
  range, compteurs journaliers, `_system_on`) reste une dette **séparée**, non traitée ici — voir
  audit précédent, non résolue par un warmup indicateur plus long (le state n'est jamais rejoué
  avant `loop_start`, quelle que soit sa valeur).
- La politique de refus explicite en cas d'historique insuffisant (`InsufficientWarmupHistory`)
  reste hors scope — comportement legacy généralisé conservé (`loop_start = max(exec_start_idx,
  warmup)`, retarde silencieusement, jamais d'exception nouvelle dans cette mission).
