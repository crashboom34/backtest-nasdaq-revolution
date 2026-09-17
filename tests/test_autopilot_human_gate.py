"""
tests/test_autopilot_human_gate.py — Bootstrap Autopilot V1 (2026-09-17), mission §12.

`HUMAN_GATE_REQUIRED` doit toujours porter : décision exacte, raison, recommandation, avantages,
risques, conséquences, 2-3 options max avec l'option recommandée identifiée — en français simple.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.autopilot.human_gate import HumanGateOption, HumanGateReport, format_human_gate_markdown


def _report(**kwargs):
    kwargs.setdefault("decision", "Faut-il déplacer FINAL_HOLDOUT ?")
    kwargs.setdefault("reason", "Contradiction scientifique réelle entre deux ADR.")
    kwargs.setdefault("recommendation", "Ne pas déplacer FINAL_HOLDOUT.")
    kwargs.setdefault("options", [
        HumanGateOption(label="Ne pas déplacer", pros=["Préserve l'intégrité scientifique"], cons=["Aucun"], recommended=True),
        HumanGateOption(label="Déplacer", pros=["Plus de données"], cons=["Casse la preuve existante"], recommended=False),
    ])
    kwargs.setdefault("risks", ["Perte de preuve historique si déplacé à tort."])
    kwargs.setdefault("consequences", "Bloque AF-V-02 tant que non tranché.")
    return HumanGateReport(**kwargs)


def test_human_gate_report_requires_at_least_one_option():
    with pytest.raises(ValueError):
        HumanGateReport(
            decision="x", reason="y", recommendation="z", options=[], risks=[], consequences="c",
        )


def test_human_gate_report_requires_at_most_three_options():
    options = [HumanGateOption(label=f"Option {i}", pros=[], cons=[], recommended=(i == 0)) for i in range(4)]
    with pytest.raises(ValueError):
        HumanGateReport(decision="x", reason="y", recommendation="z", options=options, risks=[], consequences="c")


def test_human_gate_report_requires_exactly_one_recommended_option():
    options = [
        HumanGateOption(label="A", pros=[], cons=[], recommended=False),
        HumanGateOption(label="B", pros=[], cons=[], recommended=False),
    ]
    with pytest.raises(ValueError):
        HumanGateReport(decision="x", reason="y", recommendation="z", options=options, risks=[], consequences="c")


def test_format_human_gate_markdown_contains_all_required_sections():
    report = _report()
    markdown = format_human_gate_markdown(report)
    for required in (
        "Décision", "Raison", "Recommandation", "Options", "Risques", "Conséquences",
        "Faut-il déplacer FINAL_HOLDOUT", "recommandée",
    ):
        assert required in markdown


def test_format_human_gate_markdown_marks_the_recommended_option():
    report = _report()
    markdown = format_human_gate_markdown(report)
    assert "✅" in markdown or "recommandée" in markdown


def test_a_quota_limit_or_test_failure_never_produces_a_valid_human_gate_reason():
    """Mission §12 : jamais de Human Gate pour un quota, un test rouge, un finding de review — ce
    test documente le contrat au niveau du texte (pas un mécanisme technique séparé, la
    discipline vit dans supervisor.py qui ne doit JAMAIS appeler ce module pour ces cas)."""
    forbidden_reasons = ("quota", "limite d'usage", "test rouge", "finding de review", "commit", "push")
    report = _report(reason="Contradiction scientifique réelle entre deux ADR, aucune option dominante.")
    for bad in forbidden_reasons:
        assert bad not in report.reason.lower()
