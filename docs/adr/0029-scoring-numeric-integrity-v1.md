---
status: accepted
date: 2026-11-17
---

# ADR 0029 — Intégrité numérique du scoring (`finite-metrics-v1`)

Le score pouvait récompenser une métrique invalide : `_clamp(nan)` valait 1,0, un `NaN` passait les cinq
filtres, un PF `-inf` valait comme `+inf`, un poids infini donnait 100 à tous, et un capital `NaN` était
masqué en drawdown nul par le moteur (Grand Audit, constat F-02). Nous avons décidé qu'**aucune donnée
invalide, indéfinie, absente ou incohérente ne produit de score** : elle produit un rejet typé
(`INVALID_METRIC:<code>:<champ>` ou `INVALID_CONFIG:<code>:<champ>`), et toute entrée valide garde son
score historique au bit près (1 381 vecteurs dorés produits par le code gelé `ffa987c`). Le contrat
complet (règles C1-C15, décisions U-1 à U-9, S-1, S-2, révisions 3 à 3.3) est conservé hors dépôt dans
`SCORING-INTEGRITY-CONTRACT.md` (dossier de conception du 2026-11-17).

## Décisions

- **Validation centralisée et protections internes** (option C) : `compute_score` valide configuration,
  métriques présentes (types, finitude, domaine, alias, cohérence) et paramètres avant les filtres ; il ne
  lève jamais sur une donnée. `_clamp`, la normalisation `== +inf` et la finitude du score final ferment
  les valeurs dérivées (un `rf = -inf` issu d'entrées finies vaut 0, plus 0,95). Un rejet par retour, et
  non par exception, garde le séquentiel et le parallèle identiques.
- **PF et payoff `+inf`** : légitimes seulement si `gross_win > 0` et `gross_loss == 0` ; normalisation
  0,95 et pénalité +0,10 inchangées (U-1). PF 0/0 = métrique indéfinie.
- **Frontière moteur → optimizer** (U-2 strict) : sur tout chemin scientifique, les 14 métriques du moteur
  sont exigées, le PnL et le capital doivent être finis, `len(trades) == n_trades` ; seul le zéro trade
  authentique du moteur reste « Aucun trade ». Les appels directs de `compute_score` gardent les défauts
  historiques pour une clé absente.
- **Configuration invalide** (U-3, U-4) : poids finis ≥ 0 de somme finie > 0, seuils non NaN ; refus
  avant le benchmark et l'envoi des candidats. Une erreur de worker n'est plus un candidat « score 0 » :
  les candidats en file sont annulés et l'erreur remonte, comme en séquentiel ; un candidat annulé n'est
  jamais marqué testé.
- **TEST** (U-8) : une métrique TEST invalide ou indéfinie lève `FoldTestExecutionFailed` (campagne en
  `TECHNICAL_FAILURE`), jamais un score 0, un pli sans trade ou un pli ignoré.
- **U-6 reportée** (S-1, option B) : dans le mode TRAIN/TEST legacy, un TEST techniquement invalide lève
  `LegacyTestValidationFailed` ; le job finit en erreur, ne présente aucun résultat ni rapport de
  performance, et conserve son message d'erreur. La représentation durable `None` + motif chez les
  consommateurs legacy (`optimization_store`, `job_store`, `report_generator`, `app`) reste à faire.
- **Versionnement** : `scoring_semantics_version = "finite-metrics-v1"` dans `config_used.json`, le
  manifeste Walk-Forward et l'empreinte de pli ; toute reprise legacy (optimizer, Walk-Forward,
  `train_progress.csv`) est refusée ou recalculée avant toute lecture réutilisable. Aucun format fermé
  (`validation_run.json`, B2/B3, manifestes de campagne) n'est modifié ; rupture de cohorte déclarée.
- **Provenance Gate V** (S-2, option A) : une campagne ne réutilise une preuve Walk-Forward (ni les
  preuves Monte-Carlo / Parameter Stability qui en dérivent) que si son manifeste de capture est égal,
  clé par clé, au manifeste recalculé ; sinon refus de précondition, sans mutation ni `TECHNICAL_FAILURE`.

## Conséquences

- Rupture de cohorte : un résultat legacy reste lisible et reproductible à `ffa987c`, jamais réutilisé.
- Dépendance déclarée : les lecteurs de statut et de politique Gate V ne vérifient pas la provenance ;
  aucune évaluation de politique ne peut porter sur une campagne antérieure à `finite-metrics-v1`.
- Résiduels : barres `NaN` produisant des trades finis mais faux (validation des barres en amont),
  chemin OOS FINAL_HOLDOUT (`validation_oos.py`), U-6, compteurs d'invalides sans seuil d'abandon.
