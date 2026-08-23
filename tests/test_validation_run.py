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

import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from validation_run import (
    OosValidationEvidence,
    ValidationRun,
    build_oos_validation_evidence,
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


def _run(**kwargs):
    kwargs.setdefault("validation_run_id", "val_x")
    kwargs.setdefault("research_run_id", "run_x")
    kwargs.setdefault("split_plan_id", "plan_x")
    kwargs.setdefault("dataset_snapshot_id", _SNAPSHOT_ID)
    kwargs.setdefault("strategy_name", "NASDAQ Perfect Revolution V1.1")
    kwargs.setdefault("strategy_params", {"stop_pct": 1.2, "target_pct": 6.75})
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


def test_build_validation_run_only_accepts_oos_validation_type_for_this_ticket():
    """Contrat AF-V-01 explicite : uniquement validation_type="oos" — la généralisation typée
    (Walk-Forward, Monte-Carlo...) est hors scope, réservée à AF-V-06."""
    with pytest.raises(ValueError):
        _run(validation_type="walk_forward")


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
