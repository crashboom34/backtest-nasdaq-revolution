# Mission CANARY-FINALIZATION — validation intégrée réelle (aucune valeur produit)

Ceci est une mission CANARY de validation de l'Autopilot lui-même — elle N'A AUCUNE VALEUR PRODUIT
et ne doit JAMAIS toucher au backtest, aux stratégies, à la validation scientifique, à
`FINAL_HOLDOUT`, ni à tout code/donnée en dehors du chemin explicitement autorisé ci-dessous.

## Tâches exactes (rien d'autre)

1. Le test `tests/test_canary_finalization.py::test_format_greeting_repeats_the_expected_number_of_times`
   échoue actuellement. Corrige UNIQUEMENT la fonction `format_greeting(name, times)` dans
   `scripts/autopilot/canary_fixture.py` pour qu'elle retourne le salut `"Bonjour, {name} !"`
   répété `times` fois, séparés par un espace — exactement le format attendu par ce test (lis le
   test pour voir la valeur exacte attendue).
2. Crée le fichier `.autopilot/canary/finalization_marker.md` avec EXACTEMENT ce contenu
   (remplace `<TIMESTAMP>` par l'horodatage UTC réel du moment où tu écris ce fichier, format
   ISO 8601 avec offset explicite) :

```
# Canary finalisation Autopilot

Marqueur généré automatiquement par la mission CANARY-FINALIZATION, preuve qu'un cycle réel
Developer -> Tester -> Reviewer -> Commit -> Push a fonctionné de bout en bout après les
correctifs de finalisation. Horodatage : <TIMESTAMP>.
```

N'écris et ne modifie AUCUN autre fichier. Ne touche à aucun fichier sous `strategies/`,
`results/`, `docs/adr/`, ni à `engine.py`, `optimizer.py`, `walk_forward.py`, `app.py`, ni à
`nasdaq_3m.csv`, ni à `app_corrupted_backup.py`. N'exécute pas les tests toi-même (le Tester de
l'Autopilot s'en charge séparément).
