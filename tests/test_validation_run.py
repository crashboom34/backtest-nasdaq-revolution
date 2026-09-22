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


# ═══════════════════════════════════════════════════════════════════════════════
# AF-V-02 Slice 6 — build_walk_forward_evidence() : assemblage de la preuve + verdict
# scientifique (ADR 0021 Décision 13). Aucune politique concrète de seuils PASS/FAIL n'existe dans
# ce dépôt à ce jour : le verdict reste structurellement "INCONCLUSIVE" tant qu'aucune politique
# n'est enregistrée (verdict_policy_id=None), et tout verdict_policy_id fourni sur un run complet
# lève UnknownVerdictPolicy plutôt qu'un verdict inventé — voir mission Slice 6.
# ═══════════════════════════════════════════════════════════════════════════════


def test_build_walk_forward_evidence_without_policy_is_inconclusive():
    from validation_run import WalkForwardRunOutcome, build_walk_forward_evidence

    outcome = WalkForwardRunOutcome(fold_results=(), stopped_early=False)
    evidence = build_walk_forward_evidence(outcome, aggregate=None, verdict_policy_id=None)

    assert evidence.scientific_verdict == "INCONCLUSIVE"
    assert len(evidence.verdict_reasons) > 0
    assert evidence.execution_status == "completed"


def test_build_walk_forward_evidence_execution_status_reflects_stopped_early():
    from validation_run import WalkForwardRunOutcome, build_walk_forward_evidence

    outcome = WalkForwardRunOutcome(fold_results=(), stopped_early=True)
    evidence = build_walk_forward_evidence(outcome, aggregate=None, verdict_policy_id=None)

    assert evidence.execution_status == "stopped_early"
    assert evidence.scientific_verdict == "INCONCLUSIVE"


def test_build_walk_forward_evidence_with_policy_on_complete_run_raises_unknown_verdict_policy():
    """Aucune politique concrète n'est enregistrée dans ce dépôt — un verdict_policy_id fourni sur
    un run complet (stopped_early=False) doit lever explicitement, jamais retomber silencieusement
    sur INCONCLUSIVE ni inventer un verdict PASS/FAIL."""
    from validation_run import (
        UnknownVerdictPolicy,
        WalkForwardRunOutcome,
        build_walk_forward_evidence,
    )

    outcome = WalkForwardRunOutcome(fold_results=(), stopped_early=False)
    with pytest.raises(UnknownVerdictPolicy):
        build_walk_forward_evidence(outcome, aggregate=None, verdict_policy_id="some_policy_v1")


def test_build_walk_forward_evidence_stopped_early_with_policy_stays_inconclusive_not_unknown_policy():
    """Distingue explicitement ce cas du précédent (policy fournie + run COMPLET -> exception) :
    un run interrompu (stopped_early=True) reste INCONCLUSIVE même avec un verdict_policy_id
    fourni — jamais UnknownVerdictPolicy dans ce cas précis (ADR 0021 Décision 13, mission Slice 6
    §1.b : le stopped_early prime sur la présence d'une politique)."""
    from validation_run import WalkForwardRunOutcome, build_walk_forward_evidence

    outcome = WalkForwardRunOutcome(fold_results=(), stopped_early=True)
    evidence = build_walk_forward_evidence(
        outcome, aggregate=None, verdict_policy_id="some_policy_v1",
    )

    assert evidence.scientific_verdict == "INCONCLUSIVE"
    assert evidence.execution_status == "stopped_early"


def test_build_walk_forward_evidence_passes_through_facts_unchanged():
    """fold_results/aggregate sont des faits transmis tels quels — jamais recalculés ni filtrés par
    build_walk_forward_evidence()."""
    from validation_run import AggregateResult, WalkForwardRunOutcome, build_walk_forward_evidence

    fold_results = ("sentinel_fold_result",)
    aggregate = AggregateResult(
        n_folds=1, n_folds_zero_trade=0, total_oos_trades=10, oos_net_return_pct=1.0,
        oos_max_dd_pct=0.5, oos_profit_factor=1.5, oos_win_rate=0.6, oos_sharpe=None,
        mean_fold_score_test=0.5, median_fold_score_test=0.5, worst_fold_id="fold_000",
    )
    outcome = WalkForwardRunOutcome(fold_results=fold_results, stopped_early=False)

    evidence = build_walk_forward_evidence(outcome, aggregate=aggregate, verdict_policy_id=None)

    assert evidence.fold_results == fold_results
    assert evidence.aggregate is aggregate


def test_save_and_load_round_trips_evidence_built_via_build_walk_forward_evidence(tmp_path):
    """Round-trip réel sur disque (build_validation_run() -> save_validation_run() ->
    load_validation_run()) d'une WalkForwardEvidence produite par build_walk_forward_evidence() —
    distinct du round-trip déjà couvert plus haut, qui construit la WalkForwardEvidence à la main."""
    from validation_run import WalkForwardRunOutcome, build_walk_forward_evidence

    outcome = WalkForwardRunOutcome(fold_results=(), stopped_early=False)
    evidence = build_walk_forward_evidence(outcome, aggregate=None, verdict_policy_id=None)

    run = _run(
        validation_run_id="val_wf_evidence",
        validation_type="walk_forward",
        specification=_walk_forward_specification(),
        evidence=evidence,
    )
    path = tmp_path / "wf_evidence_run.json"
    save_validation_run(path, run)

    loaded = load_validation_run(path)

    assert loaded.evidence.scientific_verdict == "INCONCLUSIVE"
    assert loaded.evidence.execution_status == "completed"
    assert list(loaded.evidence.verdict_reasons) == list(evidence.verdict_reasons)
    assert loaded.evidence.aggregate is None
    assert list(loaded.evidence.fold_results) == []


# ═══════════════════════════════════════════════════════════════════════════════
# AF-V-03 Slice 1 — registre étendu avec "monte_carlo" (MonteCarloSpecification/Evidence),
# docs/adr/0022-monte-carlo-trade-resampling-v1.md Décision 11. Uniquement la FORME typée +
# build_monte_carlo_specification() (dérivation déterministe de master_seed, Décision 5) — aucun
# algorithme de rééchantillonnage ici (monte_carlo.py, AF-V-03 Slice 2).
# ═══════════════════════════════════════════════════════════════════════════════


def _distribution_summary(**kwargs):
    from validation_run import PercentileDistributionSummary
    kwargs.setdefault("p5", 1.0)
    kwargs.setdefault("p25", 2.0)
    kwargs.setdefault("p50", 3.0)
    kwargs.setdefault("p75", 4.0)
    kwargs.setdefault("p95", 5.0)
    return PercentileDistributionSummary(**kwargs)


def _monte_carlo_specification(**kwargs):
    from validation_run import build_monte_carlo_specification
    kwargs.setdefault("source_validation_run_id", "val_x")
    kwargs.setdefault("source_trades_from_optimized_params", False)
    kwargs.setdefault("verdict_policy_id", None)
    return build_monte_carlo_specification(**kwargs)


def _monte_carlo_evidence(**kwargs):
    from validation_run import MonteCarloEvidence
    kwargs.setdefault("n_input_trades", 12)
    kwargs.setdefault("zero_trade_input", False)
    kwargs.setdefault("observed_net_ret_pct", 4.2)
    kwargs.setdefault("observed_max_dd_trade_close_basis_pct", 3.1)
    kwargs.setdefault("observed_lag1_autocorrelation", 0.05)
    kwargs.setdefault("observed_longest_losing_streak", 3)
    kwargs.setdefault("sequence_risk_max_dd_trade_close_basis_pct", _distribution_summary())
    kwargs.setdefault(
        "sequence_risk_longest_losing_streak",
        _distribution_summary(p5=1, p25=2, p50=3, p75=4, p95=5),
    )
    kwargs.setdefault("sampling_uncertainty_net_ret_pct", _distribution_summary())
    kwargs.setdefault(
        "sampling_uncertainty_max_dd_trade_close_basis_pct", _distribution_summary()
    )
    kwargs.setdefault("execution_status", "completed")
    kwargs.setdefault("scientific_verdict", "INCONCLUSIVE")
    kwargs.setdefault("verdict_reasons", ("aucune politique de verdict enregistrée",))
    return MonteCarloEvidence(**kwargs)


def test_monte_carlo_validation_type_is_registered():
    from validation_run import VALIDATION_TYPE_MONTE_CARLO
    assert VALIDATION_TYPE_MONTE_CARLO == "monte_carlo"


def test_monte_carlo_distribution_summary_is_an_explicit_type_not_an_opaque_dict():
    from validation_run import PercentileDistributionSummary
    assert isinstance(_distribution_summary(), PercentileDistributionSummary)


def test_monte_carlo_semantics_mismatch_is_a_value_error_subclass():
    from validation_run import MonteCarloSemanticsMismatch
    assert issubclass(MonteCarloSemanticsMismatch, ValueError)


@pytest.mark.parametrize("bad_id", ["", "   ", None])
def test_build_monte_carlo_specification_requires_a_real_source_validation_run_id(bad_id):
    """ADR 0022 Décision 5 — ValueError immédiat, AVANT tout calcul (master_seed en dépend
    directement), mirroring le garde-fou dataset_snapshot_id de build_validation_run()."""
    from validation_run import build_monte_carlo_specification

    with pytest.raises(ValueError):
        build_monte_carlo_specification(
            source_validation_run_id=bad_id, source_trades_from_optimized_params=False,
        )


def test_build_monte_carlo_specification_derives_the_same_master_seed_for_the_same_source_id():
    """Déterminisme (ADR 0022 Décision 5/13) : master_seed dépend UNIQUEMENT de
    source_validation_run_id, jamais de source_trades_from_optimized_params (variée ici pour le
    prouver)."""
    from validation_run import build_monte_carlo_specification

    spec_a = build_monte_carlo_specification(
        source_validation_run_id="val_same", source_trades_from_optimized_params=False,
    )
    spec_b = build_monte_carlo_specification(
        source_validation_run_id="val_same", source_trades_from_optimized_params=True,
    )
    assert spec_a.master_seed == spec_b.master_seed


def test_build_monte_carlo_specification_derives_different_master_seeds_for_different_source_ids():
    """Anti "seed shopping" (finding MAJOR M4, revue scientifique indépendante) : deux
    source_validation_run_id différents produisent des master_seed différents."""
    from validation_run import build_monte_carlo_specification

    spec_a = build_monte_carlo_specification(
        source_validation_run_id="val_a", source_trades_from_optimized_params=False,
    )
    spec_b = build_monte_carlo_specification(
        source_validation_run_id="val_b", source_trades_from_optimized_params=False,
    )
    assert spec_a.master_seed != spec_b.master_seed


def test_build_monte_carlo_specification_fixes_n_simulations_and_semantics_version():
    """ADR 0022 Décision 4/5 — n_simulations/monte_carlo_semantics_version restent des constantes
    module, jamais des valeurs choisies par l'appelant."""
    from validation_run import (
        MONTE_CARLO_DEFAULT_N_SIMULATIONS,
        MONTE_CARLO_SEMANTICS_VERSION,
        build_monte_carlo_specification,
    )

    spec = build_monte_carlo_specification(
        source_validation_run_id="val_x", source_trades_from_optimized_params=False,
    )
    assert spec.n_simulations == MONTE_CARLO_DEFAULT_N_SIMULATIONS
    assert spec.monte_carlo_semantics_version == MONTE_CARLO_SEMANTICS_VERSION
    assert spec.verdict_policy_id is None


def test_build_monte_carlo_specification_does_not_accept_master_seed_as_a_free_parameter():
    """ADR 0022 Décision 5 (correction M4, "seed shopping") — master_seed n'est jamais un
    paramètre choisi librement par l'appelant, seulement un champ DÉRIVÉ : TypeError attendu (le
    builder n'expose pas ce paramètre), jamais une acceptation silencieuse."""
    from validation_run import build_monte_carlo_specification

    with pytest.raises(TypeError):
        build_monte_carlo_specification(
            source_validation_run_id="val_x",
            source_trades_from_optimized_params=False,
            master_seed=42,
        )


def test_build_monte_carlo_specification_does_not_accept_n_simulations_as_a_free_parameter():
    """ADR 0022 Décision 4/5 — n_simulations reste une constante module, jamais un paramètre de
    build_monte_carlo_specification() (empêcherait un appelant de rejouer avec un nombre de
    simulations différent en quête d'un résultat plus favorable)."""
    from validation_run import build_monte_carlo_specification

    with pytest.raises(TypeError):
        build_monte_carlo_specification(
            source_validation_run_id="val_x",
            source_trades_from_optimized_params=False,
            n_simulations=20_000,
        )


def test_build_validation_run_accepts_a_correct_monte_carlo_pair():
    from validation_run import (
        VALIDATION_TYPE_MONTE_CARLO,
        MonteCarloEvidence,
        MonteCarloSpecification,
    )

    run = _run(
        validation_type=VALIDATION_TYPE_MONTE_CARLO,
        specification=_monte_carlo_specification(),
        evidence=_monte_carlo_evidence(),
    )
    assert run.validation_type == "monte_carlo"
    assert isinstance(run.specification, MonteCarloSpecification)
    assert isinstance(run.evidence, MonteCarloEvidence)


def test_build_validation_run_rejects_monte_carlo_specification_with_oos_evidence():
    from validation_run import VALIDATION_TYPE_MONTE_CARLO

    with pytest.raises(ValueError):
        _run(
            validation_type=VALIDATION_TYPE_MONTE_CARLO,
            specification=_monte_carlo_specification(),
            evidence=_evidence(),
        )


def test_build_validation_run_rejects_oos_specification_with_monte_carlo_evidence():
    with pytest.raises(ValueError):
        _run(
            validation_type="oos",
            specification=_specification(),
            evidence=_monte_carlo_evidence(),
        )


def test_build_validation_run_rejects_walk_forward_specification_with_monte_carlo_evidence():
    with pytest.raises(ValueError):
        _run(
            validation_type="walk_forward",
            specification=_walk_forward_specification(),
            evidence=_monte_carlo_evidence(),
        )


def test_build_validation_run_rejects_monte_carlo_specification_with_walk_forward_evidence():
    from validation_run import VALIDATION_TYPE_MONTE_CARLO

    with pytest.raises(ValueError):
        _run(
            validation_type=VALIDATION_TYPE_MONTE_CARLO,
            specification=_monte_carlo_specification(),
            evidence=_walk_forward_evidence(),
        )


def test_existing_walk_forward_validation_run_construction_is_unaffected_by_monte_carlo_registration():
    """Non-régression explicite : enregistrer "monte_carlo" ne doit rien changer aux chemins
    "oos"/"walk_forward" déjà établis (AF-V-01/AF-V-02/AF-V-06)."""
    run = _run(
        validation_type="walk_forward",
        specification=_walk_forward_specification(),
        evidence=_walk_forward_evidence(),
    )
    assert run.validation_type == "walk_forward"


def test_save_and_load_validation_run_round_trips_a_monte_carlo_run(tmp_path):
    """Round-trip réel sur disque (build_validation_run() -> save_validation_run() ->
    load_validation_run()) pour validation_type="monte_carlo" — préserve tous les champs, y
    compris les PercentileDistributionSummary imbriqués. Comme pour Walk-Forward (voir
    test_save_and_load_validation_run_round_trips_a_walk_forward_run), load_validation_run() ne
    rehydrate PAS les dataclasses imbriquées au-delà de evidence_cls(**raw_evidence) — cette
    tranche n'a pas le droit de toucher load_validation_run() (hors scope, voir mission) : les
    PercentileDistributionSummary reviennent donc comme de simples dict après un aller-retour
    JSON, jamais comme une égalité stricte d'objet. Ce test compare le CONTENU, pas l'identité de
    type — même principe déjà documenté pour fold_results/aggregate."""
    from dataclasses import asdict

    from validation_run import VALIDATION_TYPE_MONTE_CARLO

    spec = _monte_carlo_specification(source_validation_run_id="val_mc_source")
    evidence = _monte_carlo_evidence()
    run = _run(
        validation_run_id="val_mc",
        validation_type=VALIDATION_TYPE_MONTE_CARLO,
        specification=spec,
        evidence=evidence,
    )
    path = tmp_path / "mc_run.json"
    save_validation_run(path, run)

    loaded = load_validation_run(path)

    assert loaded.validation_type == "monte_carlo"
    assert loaded.specification.n_simulations == spec.n_simulations
    assert loaded.specification.master_seed == spec.master_seed
    assert loaded.specification.source_validation_run_id == spec.source_validation_run_id
    assert (
        loaded.specification.source_trades_from_optimized_params
        == spec.source_trades_from_optimized_params
    )
    assert (
        loaded.specification.monte_carlo_semantics_version
        == spec.monte_carlo_semantics_version
    )
    assert loaded.specification.verdict_policy_id == spec.verdict_policy_id

    assert loaded.evidence.n_input_trades == evidence.n_input_trades
    assert loaded.evidence.zero_trade_input == evidence.zero_trade_input
    assert loaded.evidence.observed_net_ret_pct == evidence.observed_net_ret_pct
    assert (
        loaded.evidence.observed_max_dd_trade_close_basis_pct
        == evidence.observed_max_dd_trade_close_basis_pct
    )
    assert (
        loaded.evidence.observed_lag1_autocorrelation
        == evidence.observed_lag1_autocorrelation
    )
    assert (
        loaded.evidence.observed_longest_losing_streak
        == evidence.observed_longest_losing_streak
    )
    assert loaded.evidence.execution_status == evidence.execution_status
    assert loaded.evidence.scientific_verdict == evidence.scientific_verdict
    assert list(loaded.evidence.verdict_reasons) == list(evidence.verdict_reasons)

    assert loaded.evidence.sequence_risk_max_dd_trade_close_basis_pct == asdict(
        evidence.sequence_risk_max_dd_trade_close_basis_pct
    )
    assert loaded.evidence.sequence_risk_longest_losing_streak == asdict(
        evidence.sequence_risk_longest_losing_streak
    )
    assert loaded.evidence.sampling_uncertainty_net_ret_pct == asdict(
        evidence.sampling_uncertainty_net_ret_pct
    )
    assert loaded.evidence.sampling_uncertainty_max_dd_trade_close_basis_pct == asdict(
        evidence.sampling_uncertainty_max_dd_trade_close_basis_pct
    )


def test_save_and_load_validation_run_round_trips_a_monte_carlo_zero_trade_run(tmp_path):
    """zero_trade_input=True -> tous les champs de percentiles/observed_* valent None (ADR 0022
    Décision 7) — vérifie que ce None round-trip fidèlement, distinct du cas peuplé ci-dessus."""
    from validation_run import VALIDATION_TYPE_MONTE_CARLO

    spec = _monte_carlo_specification(source_validation_run_id="val_mc_zero")
    evidence = _monte_carlo_evidence(
        n_input_trades=0,
        zero_trade_input=True,
        observed_net_ret_pct=None,
        observed_max_dd_trade_close_basis_pct=None,
        observed_lag1_autocorrelation=None,
        observed_longest_losing_streak=None,
        sequence_risk_max_dd_trade_close_basis_pct=None,
        sequence_risk_longest_losing_streak=None,
        sampling_uncertainty_net_ret_pct=None,
        sampling_uncertainty_max_dd_trade_close_basis_pct=None,
    )
    run = _run(
        validation_run_id="val_mc_zero",
        validation_type=VALIDATION_TYPE_MONTE_CARLO,
        specification=spec,
        evidence=evidence,
    )
    path = tmp_path / "mc_zero_run.json"
    save_validation_run(path, run)

    loaded = load_validation_run(path)

    assert loaded.evidence.zero_trade_input is True
    assert loaded.evidence.n_input_trades == 0
    assert loaded.evidence.observed_net_ret_pct is None
    assert loaded.evidence.sequence_risk_max_dd_trade_close_basis_pct is None
    assert loaded.evidence.sampling_uncertainty_net_ret_pct is None


# ═══════════════════════════════════════════════════════════════════════════════
# AF-V-04 Slice 1 — registre étendu avec "parameter_stability"
# (ParameterStabilitySpecification/Evidence), docs/adr/0023-parameter-stability-plateau-v1.md
# Décision 11. Uniquement la FORME typée + build_parameter_stability_specification() (validation
# de search_mode, Décision 9) — aucun algorithme de ré-analyse de voisinage ici
# (parameter_stability.py, AF-V-04 Slice 2).
# ═══════════════════════════════════════════════════════════════════════════════


def _parameter_stability_specification(**kwargs):
    from validation_run import build_parameter_stability_specification
    kwargs.setdefault("source_validation_run_id", "val_x")
    kwargs.setdefault("search_mode", "single_var")
    kwargs.setdefault("source_candidates_from_optimized_search", False)
    kwargs.setdefault("verdict_policy_id", None)
    return build_parameter_stability_specification(**kwargs)


def _parameter_stability_evidence(**kwargs):
    from validation_run import ParameterStabilityEvidence
    kwargs.setdefault("n_candidates_total", 40)
    kwargs.setdefault("zero_candidates_input", False)
    kwargs.setdefault("search_mode", "single_var")
    kwargs.setdefault("neighborhood_applicability", "local_neighborhood_available")
    kwargs.setdefault("best_score", 72.5)
    kwargs.setdefault("best_params", {"stop_pct": 1.2, "target_pct": 6.75})
    kwargs.setdefault("sensitivity", {"stop_pct": 0.31, "target_pct": 0.12})
    kwargs.setdefault("sensitivity_sample_size_by_param", {"stop_pct": 8, "target_pct": 8})
    kwargs.setdefault("n_neighbors_total_by_param", {"stop_pct": 6, "target_pct": 5})
    kwargs.setdefault("n_neighbors_rejected_by_param", {"stop_pct": 1, "target_pct": 0})
    kwargs.setdefault(
        "degradation_by_param",
        {"stop_pct": _distribution_summary(), "target_pct": _distribution_summary()},
    )
    kwargs.setdefault(
        "degradation_points_by_param",
        {"stop_pct": _distribution_summary(), "target_pct": _distribution_summary()},
    )
    kwargs.setdefault("n_hamming_le_2_total", 14)
    kwargs.setdefault("n_hamming_le_2_rejected", 2)
    kwargs.setdefault("degradation_hamming_le_2", _distribution_summary())
    kwargs.setdefault("execution_status", "completed")
    kwargs.setdefault("scientific_verdict", "INCONCLUSIVE")
    kwargs.setdefault("verdict_reasons", ("aucune politique de verdict enregistrée",))
    return ParameterStabilityEvidence(**kwargs)


def test_parameter_stability_validation_type_is_registered():
    from validation_run import VALIDATION_TYPE_PARAMETER_STABILITY
    assert VALIDATION_TYPE_PARAMETER_STABILITY == "parameter_stability"


def test_parameter_stability_semantics_mismatch_is_a_value_error_subclass():
    from validation_run import ParameterStabilitySemanticsMismatch
    assert issubclass(ParameterStabilitySemanticsMismatch, ValueError)


def test_parameter_stability_evidence_is_an_explicit_type_not_an_opaque_dict():
    from validation_run import ParameterStabilityEvidence
    assert isinstance(_parameter_stability_evidence(), ParameterStabilityEvidence)


@pytest.mark.parametrize("search_mode", ["single_var", "cross_zone", "grid", "general"])
def test_build_parameter_stability_specification_accepts_the_four_real_search_modes(search_mode):
    """ADR 0023 Décision 9 — valeurs EXACTEMENT identiques à
    `optimizer.DETERMINISTIC_DISPATCH_MODES ∪ {"general"}`, jamais un ensemble inventé."""
    spec = _parameter_stability_specification(search_mode=search_mode)
    assert spec.search_mode == search_mode


@pytest.mark.parametrize(
    "bad_mode", ["", "random", "GRID", "single-var", "bayesian", None],
)
def test_build_parameter_stability_specification_rejects_invalid_search_modes(bad_mode):
    with pytest.raises(ValueError):
        _parameter_stability_specification(search_mode=bad_mode)


@pytest.mark.parametrize("bad_id", ["", "   ", None])
def test_build_parameter_stability_specification_requires_a_real_source_validation_run_id(bad_id):
    """ADR 0023 Décision 9/11 — ValueError immédiat, AVANT tout calcul, mirroring le garde-fou de
    build_monte_carlo_specification()."""
    with pytest.raises(ValueError):
        _parameter_stability_specification(source_validation_run_id=bad_id)


def test_build_parameter_stability_specification_fixes_the_semantics_version():
    """ADR 0023 Décision 11 — parameter_stability_semantics_version reste une constante module,
    jamais une valeur choisie par l'appelant."""
    from validation_run import (
        PARAMETER_STABILITY_SEMANTICS_VERSION,
        build_parameter_stability_specification,
    )

    spec = build_parameter_stability_specification(
        source_validation_run_id="val_x",
        search_mode="grid",
        source_candidates_from_optimized_search=True,
    )
    assert spec.parameter_stability_semantics_version == PARAMETER_STABILITY_SEMANTICS_VERSION
    assert spec.verdict_policy_id is None


def test_build_parameter_stability_specification_does_not_accept_semantics_version_as_a_free_parameter():
    """ADR 0023 Décision 11 — même discipline que Monte-Carlo (n_simulations/master_seed) : un
    champ dérivé/fixé en interne n'est jamais un paramètre exposé du builder."""
    from validation_run import build_parameter_stability_specification

    with pytest.raises(TypeError):
        build_parameter_stability_specification(
            source_validation_run_id="val_x",
            search_mode="grid",
            source_candidates_from_optimized_search=True,
            parameter_stability_semantics_version="custom-version",
        )


def test_build_validation_run_accepts_a_correct_parameter_stability_pair():
    from validation_run import (
        VALIDATION_TYPE_PARAMETER_STABILITY,
        ParameterStabilityEvidence,
        ParameterStabilitySpecification,
    )

    run = _run(
        validation_type=VALIDATION_TYPE_PARAMETER_STABILITY,
        specification=_parameter_stability_specification(),
        evidence=_parameter_stability_evidence(),
    )
    assert run.validation_type == "parameter_stability"
    assert isinstance(run.specification, ParameterStabilitySpecification)
    assert isinstance(run.evidence, ParameterStabilityEvidence)


def test_build_validation_run_rejects_parameter_stability_specification_with_monte_carlo_evidence():
    from validation_run import VALIDATION_TYPE_PARAMETER_STABILITY

    with pytest.raises(ValueError):
        _run(
            validation_type=VALIDATION_TYPE_PARAMETER_STABILITY,
            specification=_parameter_stability_specification(),
            evidence=_monte_carlo_evidence(),
        )


def test_build_validation_run_rejects_monte_carlo_specification_with_parameter_stability_evidence():
    from validation_run import VALIDATION_TYPE_MONTE_CARLO

    with pytest.raises(ValueError):
        _run(
            validation_type=VALIDATION_TYPE_MONTE_CARLO,
            specification=_monte_carlo_specification(),
            evidence=_parameter_stability_evidence(),
        )


def test_build_validation_run_rejects_oos_specification_with_parameter_stability_evidence():
    with pytest.raises(ValueError):
        _run(
            validation_type="oos",
            specification=_specification(),
            evidence=_parameter_stability_evidence(),
        )


def test_build_validation_run_rejects_parameter_stability_specification_with_walk_forward_evidence():
    from validation_run import VALIDATION_TYPE_PARAMETER_STABILITY

    with pytest.raises(ValueError):
        _run(
            validation_type=VALIDATION_TYPE_PARAMETER_STABILITY,
            specification=_parameter_stability_specification(),
            evidence=_walk_forward_evidence(),
        )


def test_existing_monte_carlo_validation_run_construction_is_unaffected_by_parameter_stability_registration():
    """Non-régression explicite : enregistrer "parameter_stability" ne doit rien changer aux
    chemins "oos"/"walk_forward"/"monte_carlo" déjà établis."""
    from validation_run import VALIDATION_TYPE_MONTE_CARLO

    run = _run(
        validation_type=VALIDATION_TYPE_MONTE_CARLO,
        specification=_monte_carlo_specification(),
        evidence=_monte_carlo_evidence(),
    )
    assert run.validation_type == "monte_carlo"


def test_validation_specification_and_evidence_unions_include_parameter_stability():
    """Non-régression explicite de la lacune trouvée par la revue architecture d'ADR 0023
    (ValidationSpecification/ValidationEvidence jamais étendus lors de l'ajout de Monte-Carlo,
    corrigée commit 85dbba0) — jamais reproduite ici pour Parameter Stability."""
    import typing

    from validation_run import (
        ParameterStabilityEvidence,
        ParameterStabilitySpecification,
        ValidationEvidence,
        ValidationSpecification,
    )

    assert ParameterStabilitySpecification in typing.get_args(ValidationSpecification)
    assert ParameterStabilityEvidence in typing.get_args(ValidationEvidence)


def test_save_and_load_validation_run_round_trips_a_parameter_stability_run(tmp_path):
    """Round-trip réel sur disque (build_validation_run() -> save_validation_run() ->
    load_validation_run()) pour validation_type="parameter_stability" — préserve TOUS les champs,
    y compris les deux dictionnaires n_neighbors_total_by_param/n_neighbors_rejected_by_param
    séparés (Décision 2/6, correction BLOCKER B1), les PercentileDistributionSummary imbriqués par
    paramètre, et le signal joint degradation_hamming_le_2 (Décision 2/6, correction N1). Comme
    pour Monte-Carlo, load_validation_run() ne rehydrate pas les dataclasses imbriquées au-delà de
    evidence_cls(**raw_evidence) — ce test compare le CONTENU, pas l'identité de type."""
    from dataclasses import asdict

    from validation_run import VALIDATION_TYPE_PARAMETER_STABILITY

    spec = _parameter_stability_specification(source_validation_run_id="val_ps_source")
    evidence = _parameter_stability_evidence()
    run = _run(
        validation_run_id="val_ps",
        validation_type=VALIDATION_TYPE_PARAMETER_STABILITY,
        specification=spec,
        evidence=evidence,
    )
    path = tmp_path / "ps_run.json"
    save_validation_run(path, run)

    loaded = load_validation_run(path)

    assert loaded.validation_type == "parameter_stability"
    assert loaded.specification.source_validation_run_id == spec.source_validation_run_id
    assert loaded.specification.search_mode == spec.search_mode
    assert (
        loaded.specification.source_candidates_from_optimized_search
        == spec.source_candidates_from_optimized_search
    )
    assert (
        loaded.specification.parameter_stability_semantics_version
        == spec.parameter_stability_semantics_version
    )
    assert loaded.specification.verdict_policy_id == spec.verdict_policy_id

    assert loaded.evidence.n_candidates_total == evidence.n_candidates_total
    assert loaded.evidence.zero_candidates_input == evidence.zero_candidates_input
    assert loaded.evidence.search_mode == evidence.search_mode
    assert loaded.evidence.neighborhood_applicability == evidence.neighborhood_applicability
    assert loaded.evidence.best_score == evidence.best_score
    assert loaded.evidence.best_params == evidence.best_params
    assert loaded.evidence.sensitivity == evidence.sensitivity
    assert (
        loaded.evidence.sensitivity_sample_size_by_param
        == evidence.sensitivity_sample_size_by_param
    )
    assert loaded.evidence.n_neighbors_total_by_param == evidence.n_neighbors_total_by_param
    assert loaded.evidence.n_neighbors_rejected_by_param == evidence.n_neighbors_rejected_by_param
    assert loaded.evidence.n_hamming_le_2_total == evidence.n_hamming_le_2_total
    assert loaded.evidence.n_hamming_le_2_rejected == evidence.n_hamming_le_2_rejected
    assert loaded.evidence.execution_status == evidence.execution_status
    assert loaded.evidence.scientific_verdict == evidence.scientific_verdict
    assert list(loaded.evidence.verdict_reasons) == list(evidence.verdict_reasons)

    assert loaded.evidence.degradation_by_param == {
        param: asdict(summary) for param, summary in evidence.degradation_by_param.items()
    }
    assert loaded.evidence.degradation_points_by_param == {
        param: asdict(summary) for param, summary in evidence.degradation_points_by_param.items()
    }
    assert loaded.evidence.degradation_hamming_le_2 == asdict(evidence.degradation_hamming_le_2)


def test_save_and_load_validation_run_round_trips_a_parameter_stability_zero_candidates_run(tmp_path):
    """zero_candidates_input=True -> tous les champs Optional valent None (ADR 0023 Décision 7),
    compteurs non-Optional restent honnêtement à 0 — distinct du cas peuplé ci-dessus."""
    from validation_run import VALIDATION_TYPE_PARAMETER_STABILITY

    spec = _parameter_stability_specification(source_validation_run_id="val_ps_zero")
    evidence = _parameter_stability_evidence(
        n_candidates_total=0,
        zero_candidates_input=True,
        best_score=None,
        best_params=None,
        sensitivity={},
        sensitivity_sample_size_by_param={},
        n_neighbors_total_by_param={},
        n_neighbors_rejected_by_param={},
        degradation_by_param={},
        degradation_points_by_param={},
        n_hamming_le_2_total=0,
        n_hamming_le_2_rejected=0,
        degradation_hamming_le_2=None,
    )
    run = _run(
        validation_run_id="val_ps_zero",
        validation_type=VALIDATION_TYPE_PARAMETER_STABILITY,
        specification=spec,
        evidence=evidence,
    )
    path = tmp_path / "ps_zero_run.json"
    save_validation_run(path, run)

    loaded = load_validation_run(path)

    assert loaded.evidence.zero_candidates_input is True
    assert loaded.evidence.n_candidates_total == 0
    assert loaded.evidence.best_score is None
    assert loaded.evidence.best_params is None
    assert loaded.evidence.degradation_hamming_le_2 is None
    assert loaded.evidence.n_hamming_le_2_total == 0
