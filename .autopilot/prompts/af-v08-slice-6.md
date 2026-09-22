# Mission AF-V-08 Slice 6 — Intégration bout-en-bout, garde-fous anti-déclenchement, frontière de confiance (ADR 0024 Décisions 9/10/11/12/13)

**Lire intégralement `docs/adr/0024-gate-v-campaign-orchestration-v1.md` avant de commencer,
notamment les Décisions 9 (référence OOS jamais déclenchée), 10 (portée exacte FINAL_HOLDOUT), 11
(aucun déclenchement automatique), 12 (doublures) et la matrice complète de la Décision 13.**
AF-V-08 Slices 1-5 sont terminées et poussées — NE PAS les modifier. `execute_gate_v_campaign()`
est désormais fonctionnellement complète (WF + MC + PS + calcul du statut) ; cette tranche ferme
l'implémentation `NOT STARTED` -> terminée en ajoutant les tests de sécurité/intégration restants
de la Décision 13 qui n'ont pas encore de couverture dédiée, et en verrouillant les derniers
garde-fous structurels.

## Ce qui est DANS cette tranche

Aucune nouvelle fonctionnalité dans `gate_v_campaign.py` sauf si un test ci-dessous révèle un gap
réel (auquel cas le corriger MINIMALEMENT, sans scope creep, et documenter pourquoi dans le commit) :

1. **Test d'intégration bout-en-bout complet** (Décision 12/13, ligne finale) : `build_gate_v_campaign_plan()`
   -> `execute_gate_v_campaign()` avec des doublures `run_walk_forward_fn`/`resume_walk_forward_fn`
   FACTICES couvrant 2-3 folds -> vérifie que le pipeline ENTIER produit `walk_forward_validation_run_id`
   + `monte_carlo_validation_run_id` + `len(parameter_stability_validation_run_ids_by_fold) == len(expected_fold_ids)`
   + `status == "EVIDENCE_COMPLETE_AWAITING_POLICY"` (folds factices construits pour satisfaire la
   condition de qualité ADR 0023 Décision 3) — SANS jamais toucher `engine.py`/`nasdaq_3m.csv`.
   Variante symétrique : au moins un fold factice `neighborhood_applicability="global_correlation_only"`
   -> pipeline complet mais `status == "EVIDENCE_INCOMPLETE"`.
2. **Aucun déclenchement automatique (Décision 11)** : test d'absence d'import de `gate_v_campaign`
   dans `scripts/autopilot/` (`grep`/analyse d'imports sur tous les fichiers `.py` de ce répertoire —
   jamais un simple `grep` textuel fragile, utiliser `ast`/`importlib` si possible pour éviter les
   faux négatifs sur un import multi-lignes ou un alias).
3. **Référence OOS jamais déclenchée (Décision 9)** : test explicite — `build_gate_v_campaign_plan()`
   avec un `oos_evidence_validation_run_id` réel fourni N'APPELLE JAMAIS `validation_oos.run_oos_validation`
   (spy/mock sur ce nom si importé ailleurs dans le process de test, ou test d'absence d'import déjà
   couvert par Slice 1 — vérifier qu'aucun test existant ne laisse ce cas non couvert).
4. **Reproductibilité exacte du plan/identifiants (Décision 13)** : si non déjà couvert par Slice 1,
   ajouter le test manquant — deux appels à `build_gate_v_campaign_plan()` avec les MÊMES entrées
   produisent des `campaign_id`/`expected_fold_ids` IDENTIQUES.
5. **Aucune déclaration PASS automatique** : test GLOBAL sur TOUT le module `gate_v_campaign.py` —
   parcourt le code source, confirme qu'AUCUNE ligne ne compare une valeur à la chaîne `"PASS"`/`"FAIL"`
   pour en dériver `manifest.status` (au-delà du test déjà écrit en Slice 2 sur
   `derive_gate_v_campaign_status()` isolément — celui-ci couvre le MODULE ENTIER, y compris
   `execute_gate_v_campaign()`).
6. **Portée exacte de la frontière de confiance (Décision 10)** : test/documentation explicite (peut
   être un test qui échoue intentionnellement si `gate_v_campaign.py` importait un jour
   `validation_oos`, DÉJÀ couvert — cette tranche vérifie seulement qu'aucune régression n'a été
   introduite par les Slices 3-5, qui ont ajouté des appels réels à `walk_forward.py`/`monte_carlo.py`/
   `parameter_stability.py`/`validation_run.py` — reconfirmer le test d'import statique une dernière
   fois sur le module FINAL, pas seulement sa version Slice 1).
7. **Revue de la matrice complète de la Décision 13** : parcourir CHAQUE ligne, confirmer qu'un test
   RÉEL et NOMMÉ existe dans `tests/test_gate_v_campaign.py` pour chacune (lister explicitement, dans
   le message de commit, la correspondance ligne-de-la-Décision-13 -> nom du test réel — aucune ligne
   sans couverture ne doit rester silencieuse).

## Ce qui N'EST PAS dans cette tranche (explicitement exclu)

- Tout nouveau comportement scientifique/algorithmique — cette tranche FERME l'implémentation, elle
  n'en ouvre pas de nouvelle.
- `AF-V-07` (`ValidationPolicyVersion`) — hors scope, dépendance non bloquante documentée par l'ADR
  Décision 15/Conséquences.
- Le futur script d'appel réel de `execute_gate_v_campaign()` (le seul point d'entrée manuel explicite
  mentionné Décision 11) — n'existe pas, ne doit PAS être créé par cette tranche.
- Toute exécution réelle sur `nasdaq_3m.csv` — cette tranche ne lève JAMAIS l'interdiction, même pour
  "juste vérifier que ça marche" — tous les tests restent sur doublures.

## Contraintes absolues (héritées de la discipline du dépôt, non négociables)

- TDD strict pour tout code effectivement ajouté (RED confirmé avant l'implémentation) — si aucun gap
  n'est trouvé, cette tranche peut se limiter à AJOUTER les tests manquants sans toucher au code de
  production, ce qui est un résultat parfaitement valide et attendu.
- Suite complète verte avant de clore la tranche (tests ciblés d'abord, puis régression complète, y
  compris TOUS les tests de Slices 1-5, jamais modifiés).
- Ne rien déclarer `PASS`/robuste — `AF-V-08` passe `implementation: NOT STARTED` -> `DONE` dans
  `docs/roadmap/EPICS_AND_TICKETS.md` UNIQUEMENT si cette tranche ferme la matrice Décision 13 dans
  son intégralité ; le statut GATE V lui-même (Décision 15) reste hors de portée de tout code.
- Aucune exécution réelle sur `nasdaq_3m.csv`, aucun backtest, aucune recherche `Optimizer`, aucun
  téléchargement, aucun accès `FINAL_HOLDOUT` — dernière tranche, même discipline que les 5
  précédentes, sans exception.
