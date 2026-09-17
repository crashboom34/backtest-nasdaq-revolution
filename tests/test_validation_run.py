"""
tests/test_validation_run.py — AF-V-01 : ValidationRun / OosValidationEvidence, première
ValidationRun réelle (Track V, après Track R Foundation = COMPLETE).

ValidationRun = enregistrement immuable d'une exécution de validation précise (ici, uniquement
`validation_type="oos"` — pas un framework générique, AF-V-06 traitera la généralisation typée
future). Référence DIRECTEMENT research_run_id, split_plan_id, dataset_snapshot_id (jamais par
jointure implicite — même principe que HoldoutAccessEvent, AF-R-03). Porte une
OosValidationEvidence imbriquée : uniquement des métriques factuelles déjà natives du moteur
(engine.py::_compute_stats()), jamais un jugement subjectif "robuste"/"champion".

Aucune base de données, aucune UI : persistance fichier pure (motif atomic_json_store.py déjà
établi), testée avec tmp_path/valeurs synthétiques uniquement — aucun accès à nasdaq_3m.csv ici.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from validation_run import (
    IncoherentValidationRunError,
    OosValidationEvidence,
    OosValidationSpecification,
    ValidationRun,
    build_oos_validation_evidence,
    build_oos_validation_specification,
    build_validation_run,
    load_validation_run,
    save_validation_run,
)

_SNAPSHOT_ID = "local_csv:sha256:" + "ab" * 32


def _evidence(**kwargs):
    kwargs.setdefault("period_start", "2025-05-19T00:00:00+00:00")
    kwargs.setdefault("period_end", "2026-05-20T00:00:00+00:00")
    kwargs.setdefault("n_trades", 12)
    kwargs.setdefault("net_ret_pct", 4.2)
    return build_oos_validation_evidence(**kwargs)


def _specification(**kwargs):
    kwargs.setdefault("holdout_start", "2025-05-19T00:00:00+00:00")
    kwargs.setdefault("holdout_end", "2026-05-20T00:00:00+00:00")
    return build_oos_validation_specification(**kwargs)


def _run(**kwargs):
    kwargs.setdefault("validation_run_id", "val_x")
    kwargs.setdefault("research_run_id", "run_x")
    kwargs.setdefault("split_plan_id", "plan_x")
    kwargs.setdefault("dataset_snapshot_id", _SNAPSHOT_ID)
    kwargs.setdefault("strategy_name", "NASDAQ Perfect Revolution V1.1")
    kwargs.setdefault("strategy_params", {"stop_pct": 1.2, "target_pct": 6.75})
    kwargs.setdefault("specification", _specification())
    kwargs.setdefault("evidence", _evidence())
    return build_validation_run(**kwargs)


# ═══════════════════════════════════════════════════════════════════════════════
# A. Construction d'une ValidationRun OOS minimale
# ═══════════════════════════════════════════════════════════════════════════════


def test_build_validation_run_minimal():
    """A. Construction minimale — validation_type fixé à "oos" pour ce ticket."""
    run = _run()

    assert run.validation_run_id == "val_x"
    assert run.validation_type == "oos"
    assert run.status == "completed"
    assert run.completed_at  # horodatage auto-rempli


@pytest.mark.parametrize("bad_id", ["../escape", "val:a", "val*a", "", "   "])
def test_build_validation_run_rejects_unsafe_validation_run_id(bad_id):
    with pytest.raises(ValueError):
        _run(validation_run_id=bad_id)


# ═══════════════════════════════════════════════════════════════════════════════
# B, C, D. Liens non ambigus vers ResearchRun / DatasetSplitPlan, cohérence dataset_snapshot_id
# ═══════════════════════════════════════════════════════════════════════════════


def test_validation_run_links_to_research_run_directly():
    """B. research_run_id direct, jamais via jointure implicite."""
    run = _run(research_run_id="run_specific")

    assert run.research_run_id == "run_specific"


def test_validation_run_links_to_split_plan_directly():
    """C. split_plan_id direct."""
    run = _run(split_plan_id="plan_specific")

    assert run.split_plan_id == "plan_specific"


def test_validation_run_carries_dataset_snapshot_id_directly():
    """D. dataset_snapshot_id direct sur ValidationRun elle-même — cohérent avec le principe
    HoldoutAccessEvent (référence directe, jamais seulement via research_run_id/split_plan_id)."""
    run = _run(dataset_snapshot_id=_SNAPSHOT_ID)

    assert run.dataset_snapshot_id == _SNAPSHOT_ID


@pytest.mark.parametrize("bad_id", [None, "", "   "])
def test_build_validation_run_requires_a_real_dataset_snapshot_id(bad_id):
    with pytest.raises(ValueError):
        _run(dataset_snapshot_id=bad_id)


def test_build_validation_run_only_accepts_registered_validation_types():
    """Contrat AF-V-01/AF-V-06/AF-V-02 : seuls les types explicitement enregistrés dans
    _VALIDATION_TYPES sont acceptés — "walk_forward" est désormais enregistré (AF-V-02, ce ticket),
    ce test utilise donc un type encore non enregistré ("monte_carlo", réservé à un futur ticket)
    pour continuer à vérifier le rejet des types non enregistrés (mise à jour mécanique, 2026-09-15
    — le probe précédent, "walk_forward", n'aurait plus prouvé ce qu'il prétendait)."""
    with pytest.raises(ValueError):
        _run(validation_type="monte_carlo")


# ═══════════════════════════════════════════════════════════════════════════════
# I, J, K. OosValidationEvidence — métriques factuelles, période réellement évaluée
# ═══════════════════════════════════════════════════════════════════════════════


def test_oos_validation_evidence_is_an_explicit_type_not_an_opaque_dict():
    evidence = _evidence()

    assert isinstance(evidence, OosValidationEvidence)


def test_oos_validation_evidence_contains_the_real_period_evaluated():
    """J. La période effectivement évaluée est portée par l'evidence elle-même."""
    evidence = _evidence(
        period_start="2025-05-19T00:00:00+00:00", period_end="2026-05-20T00:00:00+00:00",
    )

    assert evidence.period_start == "2025-05-19T00:00:00+00:00"
    assert evidence.period_end == "2026-05-20T00:00:00+00:00"


def test_oos_validation_evidence_requires_offset_aware_utc_period():
    """K. Timestamps UTC offset-aware obligatoires — même discipline que SplitBoundary."""
    with pytest.raises(ValueError):
        _evidence(period_start="2025-05-19T00:00:00", period_end="2026-05-20T00:00:00+00:00")


def test_oos_validation_evidence_rejects_inverted_period():
    with pytest.raises(ValueError):
        _evidence(period_start="2026-05-20T00:00:00+00:00", period_end="2025-05-19T00:00:00+00:00")


def test_oos_validation_evidence_never_invents_a_robustness_verdict():
    """Garde-fou anti-sur-promesse (mission AF-V-01 §16) : aucun champ subjectif
    "robust"/"champion"/"score" — uniquement des métriques factuelles natives du moteur."""
    evidence = _evidence()

    for forbidden in ("robust", "robustness", "champion", "verdict", "score"):
        assert not hasattr(evidence, forbidden)


def test_oos_validation_evidence_accepts_optional_metrics_absent_on_zero_trades():
    """engine.py::_compute_stats() retourne {"n_trades": 0} SEUL quand aucun trade n'a eu lieu —
    profit_factor/win_rate/max_dd_pct doivent rester None, jamais une valeur inventée."""
    evidence = _evidence(n_trades=0, net_ret_pct=0.0)

    assert evidence.n_trades == 0
    assert evidence.profit_factor is None
    assert evidence.win_rate is None
    assert evidence.max_dd_pct is None


def test_oos_validation_evidence_preserves_an_infinite_profit_factor():
    """engine.py::_compute_stats() peut produire profit_factor=inf (aucun trade perdant) — cette
    valeur réelle ne doit pas être silencieusement convertie/perdue."""
    evidence = _evidence(profit_factor=float("inf"))

    assert evidence.profit_factor == float("inf")


# ═══════════════════════════════════════════════════════════════════════════════
# I, L, M. Persistance : immutabilité, round-trip strict
# ═══════════════════════════════════════════════════════════════════════════════


def test_save_and_load_validation_run_round_trips(tmp_path):
    """I. Persistance -> relecture strictement cohérente, y compris l'evidence imbriquée."""
    run = _run()
    path = save_validation_run(tmp_path / "validation_run.json", run)

    loaded = load_validation_run(path)

    assert loaded == run
    assert isinstance(loaded.evidence, OosValidationEvidence)


def test_save_and_load_validation_run_preserves_infinite_profit_factor(tmp_path):
    """Round-trip JSON de `float('inf')` — Python json module le supporte nativement (Infinity),
    ne doit pas être perdu/converti en None après relecture."""
    run = _run(evidence=_evidence(profit_factor=float("inf")))
    path = save_validation_run(tmp_path / "validation_run.json", run)

    loaded = load_validation_run(path)

    assert loaded.evidence.profit_factor == float("inf")


def test_load_validation_run_tolerates_missing_file(tmp_path):
    """N. Un ancien job/répertoire sans ValidationRun reste lisible, aucune exception."""
    assert load_validation_run(tmp_path / "does_not_exist.json") is None


def test_load_validation_run_tolerates_corrupted_file(tmp_path):
    path = tmp_path / "corrupted.json"
    path.write_text("{not valid json", encoding="utf-8")

    assert load_validation_run(path) is None


def test_save_validation_run_never_overwrites_an_existing_run(tmp_path):
    """L. Immutabilité — un seul ValidationRun par validation_run_id, jamais écrasé."""
    run = _run()
    path = tmp_path / "validation_run.json"
    save_validation_run(path, run)

    with pytest.raises(FileExistsError):
        save_validation_run(path, _run(strategy_name="Different Strategy"))

    # M. Le contenu original reste inchangé — jamais d'écrasement silencieux.
    assert load_validation_run(path).strategy_name == "NASDAQ Perfect Revolution V1.1"


# ═══════════════════════════════════════════════════════════════════════════════
# K. Timestamps UTC
# ═══════════════════════════════════════════════════════════════════════════════


def test_validation_run_completed_at_is_offset_aware_utc():
    run = _run()

    parsed = datetime.fromisoformat(run.completed_at)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


# ═══════════════════════════════════════════════════════════════════════════════
# P. Absence Walk-Forward/Monte-Carlo/Stress/Champion/PostgreSQL/UI
# ═══════════════════════════════════════════════════════════════════════════════


def test_validation_run_module_has_no_database_or_ui_dependency():
    import validation_run as module

    import_lines = "\n".join(
        line for line in open(module.__file__, encoding="utf-8")
        if line.strip().startswith(("import ", "from "))
    ).lower()

    assert "psycopg2" not in import_lines
    assert "sqlalchemy" not in import_lines
    assert "streamlit" not in import_lines
    assert "redis" not in import_lines
    assert "celery" not in import_lines


def test_validation_run_module_does_not_import_engine():
    """Deep module, découplé du moteur (`/codebase-design`) : validation_run.py reçoit des
    métriques déjà calculées, il ne sait pas exécuter de backtest — c'est le rôle de
    validation_oos.py (orchestration séparée)."""
    import validation_run as module

    import_lines = "\n".join(
        line for line in open(module.__file__, encoding="utf-8")
        if line.strip().startswith(("import ", "from "))
    ).lower()

    assert "engine" not in import_lines
    assert "optimizer" not in import_lines


# ═══════════════════════════════════════════════════════════════════════════════
# AF-V-06 — ValidationSpecification typée, cohérence type/specification/evidence, legacy
# ═══════════════════════════════════════════════════════════════════════════════


def test_oos_validation_specification_is_an_explicit_type_not_an_opaque_dict():
    """1. Une specification OOS est un type explicite, pas un dict opaque."""
    spec = _specification()

    assert isinstance(spec, OosValidationSpecification)


def test_oos_validation_specification_requires_offset_aware_utc_bounds():
    with pytest.raises(ValueError):
        _specification(holdout_start="2025-05-19T00:00:00", holdout_end="2026-05-20T00:00:00+00:00")


def test_oos_validation_specification_rejects_inverted_bounds():
    with pytest.raises(ValueError):
        _specification(holdout_start="2026-05-20T00:00:00+00:00", holdout_end="2025-05-19T00:00:00+00:00")


def test_oos_validation_specification_is_distinct_from_evidence():
    """La specification (ce qui devait être exécuté) et l'evidence (ce qui a été observé) restent
    deux types distincts, jamais fusionnés — même si leurs valeurs coïncident pour "oos"."""
    spec = _specification()
    evidence = _evidence()

    assert not isinstance(spec, OosValidationEvidence)
    assert not isinstance(evidence, OosValidationSpecification)


def test_build_validation_run_associates_type_specification_and_evidence_coherently():
    """3. Construction cohérente : validation_type="oos" avec une OosValidationSpecification et
    une OosValidationEvidence — le cas nominal doit réussir et porter les deux objets typés."""
    run = _run()

    assert run.validation_type == "oos"
    assert isinstance(run.specification, OosValidationSpecification)
    assert isinstance(run.evidence, OosValidationEvidence)


@pytest.mark.parametrize("bad_specification", [object(), {"holdout_start": "x", "holdout_end": "y"}])
def test_build_validation_run_rejects_specification_of_the_wrong_type(bad_specification):
    """4. Une specification qui n'est pas du type attendu par validation_type est rejetée tôt,
    jamais acceptée silencieusement (ni un dict, ni un objet arbitraire)."""
    with pytest.raises(ValueError):
        _run(specification=bad_specification)


def test_build_validation_run_rejects_evidence_swapped_with_specification():
    """4bis. Combinaison incohérente explicite : passer une OosValidationEvidence à la place de la
    specification (et réciproquement) doit échouer clairement, jamais être acceptée."""
    with pytest.raises(ValueError):
        _run(specification=_evidence())


def test_build_validation_run_rejects_evidence_of_the_wrong_type():
    with pytest.raises(ValueError):
        _run(evidence=_specification())


def test_build_validation_run_rejects_unregistered_validation_type_even_with_valid_objects():
    """Un validation_type non enregistré est rejeté même si specification/evidence sont par
    ailleurs des objets valides — AF-V-06 ne préjuge d'aucune variante future non construite ici.
    "walk_forward" (probe original) est désormais enregistré (AF-V-02) : remplacé par
    "monte_carlo", toujours non enregistré (mise à jour mécanique, 2026-09-15)."""
    with pytest.raises(ValueError):
        _run(validation_type="monte_carlo", specification=_specification(), evidence=_evidence())


def test_save_and_load_validation_run_round_trips_the_new_specification(tmp_path):
    """5. Round-trip du NOUVEAU format : la specification typée survit à l'écriture/relecture."""
    run = _run()
    path = save_validation_run(tmp_path / "validation_run.json", run)

    loaded = load_validation_run(path)

    assert loaded == run
    assert isinstance(loaded.specification, OosValidationSpecification)
    assert loaded.specification.holdout_start == run.specification.holdout_start
    assert loaded.specification.holdout_end == run.specification.holdout_end


def test_load_validation_run_tolerates_the_af_v_01_legacy_format_without_specification(tmp_path):
    """6. Lecture du format AF-V-01 LEGACY réel : aucune clé "specification" n'a jamais existé sur
    le disque avant AF-V-06 (confirmé sur les deux artefacts réels
    results/validations/*/validation_run.json, non lus/modifiés ici — fixture synthétique
    reproduisant exactement leur forme). `specification` doit être `None`, jamais reconstruite ou
    devinée à partir de l'evidence."""
    legacy_json = {
        "validation_run_id": "af-v01-ig-demo-final-holdout-oos",
        "research_run_id": "af-v01-phase-a-ig-holdout-prep",
        "split_plan_id": "af-v01-ig-demo-nasdaq-m3-2026-08",
        "dataset_snapshot_id": "ig_demo:sha256:" + "42" * 32,
        "validation_type": "oos",
        "strategy_name": "NASDAQ Perfect Revolution V1.1",
        "strategy_params": {"stop_pct": 1.2, "target_pct": 6.75},
        "evidence": {
            "period_start": "2026-08-10T17:43:30+02:00",
            "period_end": "2026-08-17T18:42:00+02:00",
            "n_trades": 0,
            "net_ret_pct": 0.0,
            "profit_factor": None,
            "win_rate": None,
            "max_dd_pct": None,
        },
        "status": "completed",
        "completed_at": "2026-08-23T08:27:48.557033+00:00",
    }
    path = tmp_path / "legacy_validation_run.json"
    path.write_text(json.dumps(legacy_json), encoding="utf-8")

    loaded = load_validation_run(path)

    assert loaded is not None
    assert loaded.specification is None  # jamais inventée pour un ancien enregistrement
    assert loaded.evidence.n_trades == 0
    assert loaded.evidence.period_start == "2026-08-10T17:43:30+02:00"
    assert loaded.validation_run_id == "af-v01-ig-demo-final-holdout-oos"


def test_load_validation_run_tolerates_a_second_legacy_shape_with_populated_metrics(tmp_path):
    """D (durcissement). Deuxième forme legacy réelle représentative (métriques réellement
    peuplées, pas seulement n_trades=0/None partout) — reproduit fidèlement
    results/validations/val_af_v_01_perfect_revolution_oos/validation_run.json (valeurs, pas le
    fichier lui-même, jamais lu ni modifié ici). Clé "specification" absente : doit rester
    `None`, jamais reconstruite depuis les métriques peuplées."""
    legacy_json = {
        "validation_run_id": "val_af_v_01_perfect_revolution_oos",
        "research_run_id": "run_af_v_01_perfect_revolution_oos",
        "split_plan_id": "split_perfect_revolution_v1_final_holdout",
        "dataset_snapshot_id": "local_csv:sha256:" + "7b" * 32,
        "validation_type": "oos",
        "strategy_name": "NASDAQ Perfect Revolution V1.1",
        "strategy_params": {"stop_pct": 1.2, "target_pct": 6.75},
        "evidence": {
            "period_start": "2025-05-19T00:00:00+00:00",
            "period_end": "2026-05-20T00:00:00+00:00",
            "n_trades": 38,
            "net_ret_pct": -2.7104728000000615,
            "profit_factor": 0.8796237492727684,
            "win_rate": 52.63157894736842,
            "max_dd_pct": 13.887489160762579,
        },
        "status": "completed",
        "completed_at": "2026-08-15T19:39:33.355874+00:00",
    }
    path = tmp_path / "legacy_populated.json"
    path.write_text(json.dumps(legacy_json), encoding="utf-8")

    loaded = load_validation_run(path)

    assert loaded is not None
    assert loaded.specification is None  # jamais reconstruite depuis des métriques peuplées
    assert loaded.evidence.n_trades == 38
    assert loaded.evidence.profit_factor == 0.8796237492727684
    assert loaded.evidence.win_rate == 52.63157894736842
    assert loaded.evidence.max_dd_pct == 13.887489160762579


def test_load_validation_run_rejects_explicit_null_specification_as_incoherent(tmp_path):
    """A (durcissement). `"specification": null` explicite, sur un validation_type enregistré
    ("oos"), n'est PAS un legacy valide — `None` n'est une représentation honnête que d'une clé
    TOTALEMENT ABSENTE (voir docstring du module). Un nouveau format qui porte `null` explicitement
    est incohérent : jamais assimilé silencieusement au legacy réel."""
    raw = {
        "validation_run_id": "val_x", "research_run_id": "run_x", "split_plan_id": "plan_x",
        "dataset_snapshot_id": _SNAPSHOT_ID, "validation_type": "oos",
        "strategy_name": "NASDAQ Perfect Revolution V1.1", "strategy_params": {},
        "specification": None,
        "evidence": {
            "period_start": "2025-05-19T00:00:00+00:00", "period_end": "2026-05-20T00:00:00+00:00",
            "n_trades": 0, "net_ret_pct": 0.0, "profit_factor": None, "win_rate": None,
            "max_dd_pct": None,
        },
        "status": "completed", "completed_at": "2026-08-23T08:27:48.557033+00:00",
    }
    path = tmp_path / "explicit_null_specification.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(IncoherentValidationRunError):
        load_validation_run(path)


def test_save_validation_run_refuses_to_persist_a_run_without_a_specification(tmp_path):
    """C (durcissement). Un run legacy relu (`specification is None`) ne peut pas être
    re-persisté tel quel — `specification=None` n'est une représentation valide qu'EN LECTURE
    d'un ancien artefact, jamais un format de création valide. Le nouveau chemin ne doit jamais
    être créé (échec avant toute écriture disque)."""
    legacy_json = {
        "validation_run_id": "val_x", "research_run_id": "run_x", "split_plan_id": "plan_x",
        "dataset_snapshot_id": _SNAPSHOT_ID, "validation_type": "oos",
        "strategy_name": "NASDAQ Perfect Revolution V1.1", "strategy_params": {},
        "evidence": {
            "period_start": "2025-05-19T00:00:00+00:00", "period_end": "2026-05-20T00:00:00+00:00",
            "n_trades": 0, "net_ret_pct": 0.0, "profit_factor": None, "win_rate": None,
            "max_dd_pct": None,
        },
        "status": "completed", "completed_at": "2026-08-23T08:27:48.557033+00:00",
    }
    legacy_path = tmp_path / "legacy.json"
    legacy_path.write_text(json.dumps(legacy_json), encoding="utf-8")
    loaded = load_validation_run(legacy_path)
    assert loaded.specification is None  # précondition du test

    new_path = tmp_path / "new_location.json"

    with pytest.raises(ValueError):
        save_validation_run(new_path, loaded)

    assert not new_path.exists()  # aucune écriture, même partielle


def test_load_validation_run_never_overwrites_or_rewrites_the_legacy_file(tmp_path):
    """7. La lecture n'écrit jamais rien — un artefact historique n'est jamais réécrit par simple
    chargement (round-trip de lecture seule : le fichier reste octet pour octet identique)."""
    legacy_json = {
        "validation_run_id": "val_x", "research_run_id": "run_x", "split_plan_id": "plan_x",
        "dataset_snapshot_id": _SNAPSHOT_ID, "validation_type": "oos",
        "strategy_name": "NASDAQ Perfect Revolution V1.1", "strategy_params": {},
        "evidence": {
            "period_start": "2025-05-19T00:00:00+00:00", "period_end": "2026-05-20T00:00:00+00:00",
            "n_trades": 0, "net_ret_pct": 0.0, "profit_factor": None, "win_rate": None,
            "max_dd_pct": None,
        },
        "status": "completed", "completed_at": "2026-08-23T08:27:48.557033+00:00",
    }
    path = tmp_path / "legacy.json"
    original_bytes = json.dumps(legacy_json).encode("utf-8")
    path.write_bytes(original_bytes)

    load_validation_run(path)

    assert path.read_bytes() == original_bytes


def test_load_validation_run_raises_on_unrecognized_validation_type(tmp_path):
    """Combinaison incohérente persistée : un validation_type non enregistré doit échouer
    clairement, jamais être silencieusement traité comme absent/None (voir docstring du module)."""
    raw = {
        "validation_run_id": "val_x", "research_run_id": "run_x", "split_plan_id": "plan_x",
        "dataset_snapshot_id": _SNAPSHOT_ID, "validation_type": "walk_forward",
        "strategy_name": "NASDAQ Perfect Revolution V1.1", "strategy_params": {},
        "specification": None,
        "evidence": {
            "period_start": "2025-05-19T00:00:00+00:00", "period_end": "2026-05-20T00:00:00+00:00",
            "n_trades": 0, "net_ret_pct": 0.0, "profit_factor": None, "win_rate": None,
            "max_dd_pct": None,
        },
        "status": "completed", "completed_at": "2026-08-23T08:27:48.557033+00:00",
    }
    path = tmp_path / "invalid_type.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(IncoherentValidationRunError):
        load_validation_run(path)


def test_load_validation_run_raises_on_specification_shape_mismatch(tmp_path):
    """Une specification structurellement incompatible avec le type enregistré pour "oos" (champs
    manquants/inattendus) doit échouer clairement plutôt que d'être silencieusement ignorée."""
    raw = {
        "validation_run_id": "val_x", "research_run_id": "run_x", "split_plan_id": "plan_x",
        "dataset_snapshot_id": _SNAPSHOT_ID, "validation_type": "oos",
        "strategy_name": "NASDAQ Perfect Revolution V1.1", "strategy_params": {},
        "specification": {"unexpected_field": "value"},
        "evidence": {
            "period_start": "2025-05-19T00:00:00+00:00", "period_end": "2026-05-20T00:00:00+00:00",
            "n_trades": 0, "net_ret_pct": 0.0, "profit_factor": None, "win_rate": None,
            "max_dd_pct": None,
        },
        "status": "completed", "completed_at": "2026-08-23T08:27:48.557033+00:00",
    }
    path = tmp_path / "bad_spec.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(IncoherentValidationRunError):
        load_validation_run(path)


# ═══════════════════════════════════════════════════════════════════════════════
# AF-V-02 Slice 1 — registre étendu avec "walk_forward" (WalkForwardSpecification/Evidence)
# ═══════════════════════════════════════════════════════════════════════════════


def _fold_definition(fold_index=0, is_last_fold=True):
    from validation_run import FoldDefinition
    return FoldDefinition(
        fold_index=fold_index, fold_id=f"fold_{fold_index:03d}",
        train_start="2020-01-01T00:00:00+00:00",
        requested_boundary="2022-01-01T00:00:00+00:00", effective_boundary="2022-01-01T00:00:00+00:00",
        boundary_adjusted=False,
        requested_test_end="2022-07-01T00:00:00+00:00", effective_test_end="2022-07-01T00:00:00+00:00",
        test_end_adjusted=False, is_last_fold=is_last_fold,
    )


def _walk_forward_specification(**kwargs):
    from validation_run import WalkForwardSpecification
    kwargs.setdefault("geometry", "rolling")
    kwargs.setdefault("train_period", "P24M")
    kwargs.setdefault("test_period", "P6M")
    kwargs.setdefault("step_period", "P6M")
    kwargs.setdefault("allow_partial_last_fold", False)
    kwargs.setdefault("position_transition_policy", "flat_each_fold_v1")
    kwargs.setdefault("walk_forward_semantics_version", "rolling-calendar-v2")
    kwargs.setdefault("base_params", {"or_start_h": 15, "or_start_m": 30})
    kwargs.setdefault("verdict_policy_id", None)
    kwargs.setdefault("master_seed", None)
    return WalkForwardSpecification(**kwargs)


def _walk_forward_evidence(**kwargs):
    from validation_run import WalkForwardEvidence
    kwargs.setdefault("fold_results", ())
    kwargs.setdefault("aggregate", None)
    kwargs.setdefault("execution_status", "completed")
    kwargs.setdefault("scientific_verdict", "INCONCLUSIVE")
    kwargs.setdefault("verdict_reasons", ("aucune politique de verdict enregistrée",))
    return WalkForwardEvidence(**kwargs)


def test_fold_definition_is_an_explicit_type_not_an_opaque_dict():
    fold = _fold_definition()
    from validation_run import FoldDefinition
    assert isinstance(fold, FoldDefinition)


def test_walk_forward_validation_type_is_registered():
    from validation_run import VALIDATION_TYPE_WALK_FORWARD
    assert VALIDATION_TYPE_WALK_FORWARD == "walk_forward"


def test_build_validation_run_accepts_a_correct_walk_forward_pair():
    run = _run(
        validation_type="walk_forward",
        specification=_walk_forward_specification(),
        evidence=_walk_forward_evidence(),
    )
    assert run.validation_type == "walk_forward"
    from validation_run import WalkForwardEvidence, WalkForwardSpecification
    assert isinstance(run.specification, WalkForwardSpecification)
    assert isinstance(run.evidence, WalkForwardEvidence)


def test_build_validation_run_rejects_walk_forward_specification_with_oos_evidence():
    """Mauvais pairing explicitement rejeté — jamais une combinaison typée incohérente acceptée."""
    with pytest.raises(ValueError):
        _run(
            validation_type="walk_forward",
            specification=_walk_forward_specification(),
            evidence=_evidence(),
        )


def test_build_validation_run_rejects_oos_specification_with_walk_forward_evidence():
    with pytest.raises(ValueError):
        _run(
            validation_type="oos",
            specification=_specification(),
            evidence=_walk_forward_evidence(),
        )


def test_existing_oos_validation_run_construction_is_unaffected_by_walk_forward_registration():
    """Non-régression explicite : enregistrer "walk_forward" ne doit rien changer au chemin "oos"
    déjà établi (AF-V-01/AF-V-06)."""
    run = _run()
    assert run.validation_type == "oos"
    assert isinstance(run.specification, OosValidationSpecification)
    assert isinstance(run.evidence, OosValidationEvidence)


def test_save_and_load_validation_run_round_trips_a_walk_forward_run(tmp_path):
    """Round-trip du contenu significatif — pas une égalité stricte d'objet : `fold_results`/
    `verdict_reasons` (`Tuple[...]`) redeviennent des `list` après un aller-retour JSON générique
    (limitation connue, pas spécifique à Walk-Forward — `load_validation_run()` ne rehydrate pas
    plus que ce que fait déjà `evidence_cls(**raw_evidence)` pour "oos"). Une rehydratation fine
    des `FoldResult`/`AggregateResult` imbriqués reste hors scope Slice 1 (`fold_results` est
    toujours vide tant qu'aucune exécution TEST réelle n'existe, voir mission section 1)."""
    run = _run(
        validation_run_id="val_wf",
        validation_type="walk_forward",
        specification=_walk_forward_specification(),
        evidence=_walk_forward_evidence(),
    )
    path = tmp_path / "wf_run.json"
    save_validation_run(path, run)

    loaded = load_validation_run(path)

    assert loaded.validation_type == "walk_forward"
    assert loaded.specification.geometry == run.specification.geometry
    assert loaded.specification.base_params == run.specification.base_params
    assert loaded.evidence.execution_status == run.evidence.execution_status
    assert loaded.evidence.scientific_verdict == run.evidence.scientific_verdict
    assert list(loaded.evidence.verdict_reasons) == list(run.evidence.verdict_reasons)
    assert list(loaded.evidence.fold_results) == list(run.evidence.fold_results)
