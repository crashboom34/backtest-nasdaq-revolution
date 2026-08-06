# Règles de génération des timeframes calendaires (semaine, mois)

Status: Proposé

L'ADR 0003 gère le resampling par multiple entier de minutes (M/H/D) mais exclut explicitement
les unités calendaires ("hors périmètre de cet ADR"). Cette évolution ajoute deux unités
calendaires : **W1** (semaine) et **MO1** (mois civil), nécessaires pour satisfaire la Phase 6
du Data Center ("les unités journalières, hebdomadaires et mensuelles sont prises en charge").

Une semaine ou un mois n'est pas un multiple entier de minutes exploitable de la même façon
qu'un timeframe intraday (un mois fait 28 à 31 jours) : une dérivation calendaire dédiée est
nécessaire plutôt que d'étendre le mécanisme M/H/D existant.

Règles retenues :

- **Source unique autorisée : D1.** W1 et MO1 ne sont dérivables qu'à partir d'un timeframe
  source **journalier (D1)**, jamais directement depuis un timeframe intraday (ex. M3). Une
  dérivation directe M3 → W1 mélangerait deux logiques d'ancrage différentes (multiple de
  minutes vs calendaire) sans garantie de cohérence — préférer un chaînage explicite (M3 → D1 →
  W1) plutôt qu'un raccourci implicite.
- **Semaine (W1)** : ancrage lundi–dimanche (règle pandas `W-SUN`, bougie étiquetée par son
  lundi de départ), toujours en UTC — même limitation que l'ADR 0003 (pas de calendrier de
  marché, donc pas d'alignement sur la semaine de trading réelle).
- **Mois (MO1)** : ancrage sur le mois civil UTC (règle pandas `MS`, bougie étiquetée par le
  1er du mois), même limitation.
- **Bougie incomplète** : pour W1/MO1, une bougie est marquée incomplète si la période
  calendaire de son dernier bucket (dimanche de la semaine / dernier jour du mois) est
  postérieure à la dernière donnée disponible dans la source — pas en comptant un nombre de
  barres attendues (qui donnerait un faux "incomplet" chaque semaine à cause des week-ends sans
  séance, en l'absence de calendrier de marché).
- **Multiplicateurs** : seuls W1 et MO1 sont pris en charge pour cette étape (pas W2, MO3...).

## Considered Options

- **Étendre le mécanisme M/H/D existant en ajoutant "W" et "MO" à la table des minutes** (semaine
  = 10080 minutes fixes, mois = ?). Rejeté pour le mois : un mois n'a pas de durée fixe en
  minutes, donc la vérification "multiple entier" perdrait tout son sens. Semaine aurait pu
  fonctionner numériquement (10080 = 1440 × 7) mais un simple découpage `resample("10080min")`
  ne s'aligne pas sur les frontières lundi–dimanche — un ancrage calendaire dédié est nécessaire
  de toute façon.
- **Compter les barres attendues pour détecter une semaine/mois incomplet, comme pour M/H/D.**
  Rejeté : sans calendrier de marché, une semaine calendaire de 7 jours n'a que 5 bougies
  quotidiennes de séance (marchés fermés le week-end) — un compteur fixe marquerait chaque
  semaine "complète" comme incomplète. La comparaison à la dernière donnée disponible est plus
  honnête tant qu'aucun calendrier de marché n'existe dans le dépôt.

## Consequences

- Un futur calendrier de marché (jours fériés, séances) pourra affiner la détection
  d'incomplétude sans changer la structure de `ResampleResult`.
- `market_data.catalog.DEFAULT_CANDIDATE_TIMEFRAMES` inclut désormais W1/MO1 : ils apparaîtront
  `not_calculable` pour tout actif dont le timeframe source n'est pas D1 (ex. NASDAQ M3), ce qui
  est le comportement attendu et documenté ci-dessus.
