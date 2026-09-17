"""
scripts/create_walk_forward_validation_split_plan.py — AF-V-02 Slice 1, prérequis d'implémentation
identifié par docs/adr/0021-walk-forward-rolling-calendar-v1.md, Décision 8.

`DatasetSplitPlan` est immuable (`save_dataset_split_plan()` refuse un `split_plan_id` déjà écrit)
et le plan historique de Perfect Revolution
(`results/dataset_splits/split_perfect_revolution_v1_final_holdout/split_plan.json`) a
`validation: null` (vérifié, jamais un consommateur réel jusqu'ici — voir ADR 0021 Décision 8).
Ce script construit un **nouveau** plan, jamais une modification rétroactive de l'ancien :

- même `dataset_snapshot_id` (référence, jamais recalculé) ;
- `final_holdout` **identique**, jamais déplacé (2025-05-19T00:00:00+00:00 →
  2026-05-20T00:00:00+00:00 dans le plan réel — règle absolue, indépendante de l'allocation
  choisie ci-dessous) ;
- `train` conservé mais raccourci (mêmes bornes de départ, fin déplacée à `VALIDATION.start`) ;
- `validation` peuplée, immédiatement contiguë à `final_holdout` (zéro écart), `[start,end)`.

**Allocation retenue pour `VALIDATION_MONTHS`** (décision d'implémentation, PAS une nouvelle borne
globale inventée — `dataset_snapshot_id` et `final_holdout` viennent du plan historique vérifié ;
seul le point de partage TRAIN/VALIDATION est une décision laissée explicitement ouverte par l'ADR
0021 Décision 8, "aucune borne précise... n'est fixée par cette ADR") : 42 mois = `train_period`
(24) + 3 × `step_period` (6) du préréglage Rolling par défaut — dimensionnée pour faire tenir
EXACTEMENT 3 folds P24M/P6M/P6M sans reliquat partiel sur CETTE allocation précise. Le mécanisme de
détection de reliquat partiel (`walk_forward.detect_partial_tail()`) reste testé séparément via des
fixtures synthétiques, indépendamment de ce choix — un futur ajustement de cette constante
n'affecterait qu'un nouveau `split_plan_id`, jamais celui déjà écrit (immuabilité).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

# Même convention que les autres scripts de ce dossier (ex. scripts/test_eodhd_connection.py) :
# permet l'exécution standalone (`python scripts/create_walk_forward_validation_split_plan.py`)
# sans dépendre du répertoire courant.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataset_split import (
    DatasetSplitPlan, build_dataset_split_plan, build_split_boundary, load_dataset_split_plan,
    save_dataset_split_plan,
)

HISTORICAL_SPLIT_PLAN_PATH = Path(
    "results/dataset_splits/split_perfect_revolution_v1_final_holdout/split_plan.json"
)
NEW_SPLIT_PLAN_ID = "split_perfect_revolution_v1_walk_forward_v1"
NEW_SPLIT_PLAN_PATH = Path(f"results/dataset_splits/{NEW_SPLIT_PLAN_ID}/split_plan.json")

VALIDATION_MONTHS = 42


def build_walk_forward_validation_split_plan(historical: DatasetSplitPlan) -> DatasetSplitPlan:
    """Fonction PURE : dérive le nouveau plan à partir d'un `DatasetSplitPlan` historique déjà
    chargé/vérifié — ne lit ni n'écrit aucun fichier, ne modifie jamais l'objet reçu (frozen).
    Suppose `historical.train`/`historical.final_holdout` présents (garanti par
    `DatasetSplitPlan` : tous deux obligatoires à la construction)."""
    old_train_end = pd.Timestamp(historical.train.end)
    validation_start_iso = (old_train_end - pd.DateOffset(months=VALIDATION_MONTHS)).isoformat()

    new_train = build_split_boundary(historical.train.start, validation_start_iso)
    new_validation = build_split_boundary(validation_start_iso, historical.train.end)

    return build_dataset_split_plan(
        split_plan_id=NEW_SPLIT_PLAN_ID,
        dataset_snapshot_id=historical.dataset_snapshot_id,
        train=new_train,
        final_holdout=historical.final_holdout,
        validation=new_validation,
        discovery_oos=None,
    )


def main() -> None:
    historical = load_dataset_split_plan(HISTORICAL_SPLIT_PLAN_PATH)
    if historical is None:
        raise SystemExit(
            f"Plan historique introuvable/illisible à {HISTORICAL_SPLIT_PLAN_PATH} — à vérifier "
            "manuellement avant de continuer ; jamais reconstruit à partir d'une hypothèse."
        )
    new_plan = build_walk_forward_validation_split_plan(historical)
    path = save_dataset_split_plan(NEW_SPLIT_PLAN_PATH, new_plan)
    print(f"Nouveau DatasetSplitPlan ecrit : {path}")
    print(f"  split_plan_id : {new_plan.split_plan_id}")
    print(f"  dataset_snapshot_id : {new_plan.dataset_snapshot_id}")
    print(f"  TRAIN         : [{new_plan.train.start}, {new_plan.train.end})")
    print(f"  VALIDATION    : [{new_plan.validation.start}, {new_plan.validation.end})")
    print(f"  FINAL_HOLDOUT : [{new_plan.final_holdout.start}, {new_plan.final_holdout.end})")
    print(f"  Plan historique ({historical.split_plan_id}) : NON MODIFIE.")


if __name__ == "__main__":
    main()
