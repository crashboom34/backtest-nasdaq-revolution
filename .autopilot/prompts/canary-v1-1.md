# Mission CANARY-V1-1 — validation intégrée réelle de l'Autopilot V1.1

Ceci est une mission CANARY : elle sert uniquement à prouver que la boucle Autopilot V1.1
fonctionne réellement de bout en bout (Developer réel, Tester réel, Reviewer indépendant réel,
commit/push réels). Elle N'A AUCUNE VALEUR PRODUIT et ne doit JAMAIS toucher au backtest, aux
stratégies, à la validation scientifique, à FINAL_HOLDOUT, ou à tout code/donnée en dehors du
chemin explicitement autorisé ci-dessous.

## Tâche exacte (aucune autre action)

Crée ou remplace le fichier `.autopilot/canary/CANARY_MARKER.md` avec EXACTEMENT ce contenu
(remplace `<TIMESTAMP>` par l'horodatage UTC réel du moment où tu écris ce fichier, format ISO 8601
avec offset explicite, par exemple `2026-09-17T18:42:00+00:00`) :

```
# Canary Autopilot V1.1

Ce fichier est un marqueur généré automatiquement par l'Autopilot V1.1 (mission CANARY-V1-1),
preuve qu'un cycle réel Developer -> Tester -> Reviewer -> Commit -> Push a fonctionné de bout en
bout. Aucune valeur produit. Horodatage : <TIMESTAMP>.
```

N'écris et ne modifie AUCUN autre fichier. Ne lance aucune commande destructive. Ne touche à
aucun fichier sous `strategies/`, `results/`, `docs/adr/`, ni à `engine.py`, `optimizer.py`,
`app.py`, ni à `nasdaq_3m.csv`, ni à `app_corrupted_backup.py`. N'exécute pas les tests toi-même
(le Tester de l'Autopilot s'en charge séparément) — contente-toi d'écrire ce seul fichier.
