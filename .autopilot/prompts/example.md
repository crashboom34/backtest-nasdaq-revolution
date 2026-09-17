# Gabarit de mission Autopilot

Ce fichier est un exemple. Le statut correspondant dans `missions.json` (`EXAMPLE-001`) est
volontairement `BLOCKED` — `select_next_mission()` ne le choisit donc jamais automatiquement.

Avant d'utiliser `autopilot start` pour de vrai :

1. Décider explicitement de la ou des vraies missions à mettre en file (ex. AF-V-02 Slice 2 —
   voir `AI_HANDOFF.md` pour l'état exact du travail précédent).
2. Écrire son prompt réel dans un nouveau fichier `.autopilot/prompts/<id>.md`.
3. Ajouter l'entrée correspondante dans `.autopilot/missions.json` avec `status: "PLANNED"`.
4. Retirer ou laisser `BLOCKED` ce gabarit (jamais le passer à `PLANNED` tel quel).

**Pourquoi la file n'est pas déjà pré-remplie avec AF-V-02 Slice 2** : ce dépôt applique depuis
le début d'AF-V-02 une discipline stricte d'autorisation explicite par tranche (chaque Slice a
toujours démarré sur un message utilisateur dédié, jamais enchaîné automatiquement). La mission de
Bootstrap Autopilot autorise largement l'autonomie technique (tests, corrections, commits, push)
mais ne tranche pas elle-même la question produit de savoir si ce rythme par tranche doit changer
— décision laissée explicitement à l'utilisateur, pas prise silencieusement ici.
