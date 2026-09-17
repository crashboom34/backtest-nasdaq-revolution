"""
scripts/autopilot/human_gate.py — Formatage d'un Human Gate (Bootstrap V1, 2026-09-17).

Mission §12 : `HUMAN_GATE_REQUIRED` est un mécanisme EXCEPTIONNEL. Ce module ne fait que
structurer/formater un rapport déjà décidé comme nécessaire par l'appelant (`supervisor.py`) — il
ne décide jamais lui-même quand déclencher un Human Gate (cette décision reste dans
`supervisor.py`, en dernier recours, jamais pour un quota/test rouge/finding de review, mission
§7/§12). Présentation en français simple, exactement les champs requis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class HumanGateOption:
    label: str
    pros: List[str]
    cons: List[str]
    recommended: bool = False


@dataclass(frozen=True)
class HumanGateReport:
    """`options` : 1 à 3 (mission §12, "deux ou trois options maximum"), exactement une marquée
    `recommended=True` — vérifié à la construction, jamais laissé incohérent."""

    decision: str
    reason: str
    recommendation: str
    options: List[HumanGateOption]
    risks: List[str]
    consequences: str

    def __post_init__(self) -> None:
        if not (1 <= len(self.options) <= 3):
            raise ValueError(
                f"Un Human Gate doit proposer entre 1 et 3 options (mission §12) — reçu "
                f"{len(self.options)}."
            )
        recommended_count = sum(1 for o in self.options if o.recommended)
        if recommended_count != 1:
            raise ValueError(
                "Un Human Gate doit identifier EXACTEMENT une option recommandée (mission §12) — "
                f"{recommended_count} trouvée(s)."
            )


def format_human_gate_markdown(report: HumanGateReport) -> str:
    """Produit le rapport Human Gate en français simple, mission §12 : décision exacte, raison,
    recommandation, avantages/risques par option, conséquences, option recommandée identifiée."""
    lines = [
        "# 🚦 HUMAN_GATE_REQUIRED",
        "",
        "## Décision",
        report.decision,
        "",
        "## Raison du blocage",
        report.reason,
        "",
        "## Recommandation de Claude",
        report.recommendation,
        "",
        "## Options",
    ]
    for option in report.options:
        marker = " — ✅ option recommandée" if option.recommended else ""
        lines.append(f"### {option.label}{marker}")
        lines.append("**Avantages** :")
        lines.extend([f"- {p}" for p in option.pros] or ["- (aucun listé)"])
        lines.append("**Risques/inconvénients** :")
        lines.extend([f"- {c}" for c in option.cons] or ["- (aucun listé)"])
        lines.append("")
    lines.append("## Risques")
    lines.extend([f"- {r}" for r in report.risks] or ["- (aucun listé)"])
    lines.append("")
    lines.append("## Conséquences")
    lines.append(report.consequences)
    return "\n".join(lines)
