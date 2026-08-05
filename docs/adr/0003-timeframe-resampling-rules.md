# Règles de génération des timeframes dérivés (resampling)

Status: Proposé

Pour éviter de devoir importer séparément chaque unité de temps (principe demandé par
l'utilisateur le 2026-08-05), nous introduisons `market_data.resample.resample_ohlcv()` : une
fonction pure qui dérive un timeframe supérieur à partir d'un DataFrame canonique
(`market_data.schema.CANONICAL_COLUMNS`) déjà chargé.

Règles retenues pour cette étape :

- **Compatibilité stricte** : un timeframe cible en minutes n'est calculable que s'il est un
  multiple entier du timeframe source en minutes (ex. source M3 → cible M15 possible car
  15 = 3 × 5 ; cible M5 refusée car 5 n'est pas un multiple de 3). Une demande incompatible
  retourne une erreur explicite (`ResampleError`), jamais un résultat silencieusement faux.
- **Ancrage UTC uniquement** : le regroupement des bougies utilise l'ancrage UTC standard de
  `pandas.DataFrame.resample()` (minuit UTC). Aucun ancrage "ouverture de séance" ni calendrier
  de marché n'est géré à ce stade — c'est une limitation connue, à lever dans une étape
  ultérieure dédiée (voir la section "Gestion du temps et des séances" de la demande initiale).
  Toute bougie dérivée porte cette hypothèse explicitement dans son message d'avertissement.
- **Bougies incomplètes en bord de série** : la dernière bougie dérivée peut être incomplète si
  la série source s'arrête au milieu d'un intervalle cible. Elle est conservée mais signalée
  (`incomplete_last_bar=True` dans le résultat), jamais supprimée silencieusement.
- **Volume** : sommé sur l'intervalle si présent, sinon laissé à NA (cohérent avec le schéma
  canonique où le volume est optionnel).

Les timeframes gérés dans cette première version sont exprimés en minutes (M1 à M1440). Les
unités calendaires (jour, semaine, mois) et les ancrages personnalisés (profil CME, IG...) sont
hors périmètre de cet ADR et feront l'objet d'une évolution séparée.

## Considered Options

- **Autoriser un resampling "best effort" même quand le timeframe cible n'est pas un multiple
  exact de la source** (ex. arrondir). Rejeté : contredit explicitement le principe demandé par
  l'utilisateur ("avec une source 5 minutes, ne pas prétendre pouvoir reconstruire les unités 1,
  2 ou 3 minutes") et introduirait des données trompeuses.
- **Gérer dès maintenant l'ancrage sur l'heure d'ouverture de marché.** Reporté : nécessite un
  calendrier de marché (jours fériés, horaires par actif), qui n'existe pas encore dans le
  dépôt. Ajouter cette gestion sans données de calendrier réelles produirait un faux sentiment
  de précision.

## Consequences

- Toute bougie dérivée doit être considérée comme approximative tant que l'ancrage n'est pas
  aligné sur le calendrier réel du marché — à rappeler dans l'UI le jour où ce module sera
  branché à l'interface.
- `market_data.derived` (cache disque des timeframes dérivés, étape suivante) doit stocker
  explicitement quel timeframe source et quelle règle d'ancrage ont produit chaque fichier en
  cache, pour permettre une invalidation propre si les règles évoluent.
