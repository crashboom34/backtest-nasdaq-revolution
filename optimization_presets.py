"""Optimization presets used by the Streamlit configuration UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


CUSTOM_PRESET_NAME = "Personnalisé"
QUICK_PRESET_NAME = "Test rapide local"


@dataclass(frozen=True)
class OptimizationPreset:
    name: str
    description: str
    max_rows: Optional[int]
    max_combinations: Optional[int]
    benchmark_n_sample: int
    workers: Optional[int]
    full_history: bool = False
    configurable_max_combinations: bool = False
    configurable_workers: bool = False
    manual_control: bool = False
    warning: str = ""


def _server_workers(cpu_count: Optional[int]) -> int:
    cpu = int(cpu_count or 4)
    return max(2, min(cpu, 16))


def get_optimization_presets(cpu_count: Optional[int] = None) -> list[OptimizationPreset]:
    """Return presets in the order displayed in Streamlit."""
    return [
        OptimizationPreset(
            name=QUICK_PRESET_NAME,
            description="Validation technique locale : petit historique, 12 combinaisons, 1 worker.",
            max_rows=20_000,
            max_combinations=12,
            workers=1,
            benchmark_n_sample=1,
        ),
        OptimizationPreset(
            name="Test moyen",
            description="Essai plus représentatif sans lancer une optimisation complète.",
            max_rows=100_000,
            max_combinations=100,
            workers=2,
            benchmark_n_sample=3,
        ),
        OptimizationPreset(
            name="Optimisation complète",
            description="Historique complet, benchmark plus fiable, nombre de workers choisi par l'utilisateur.",
            max_rows=None,
            max_combinations=None,
            workers=None,
            benchmark_n_sample=5,
            full_history=True,
            configurable_workers=True,
            warning="Peut être long : utilise tout l'historique disponible.",
        ),
        OptimizationPreset(
            name="Serveur puissant",
            description="Historique complet avec limite et workers élevés configurables.",
            max_rows=None,
            max_combinations=500_000,
            workers=_server_workers(cpu_count),
            benchmark_n_sample=5,
            full_history=True,
            configurable_max_combinations=True,
            configurable_workers=True,
            warning="Prévu pour serveur : à éviter sur un PC local lent.",
        ),
        OptimizationPreset(
            name=CUSTOM_PRESET_NAME,
            description="Contrôle manuel de toutes les limites d'optimisation.",
            max_rows=None,
            max_combinations=None,
            workers=None,
            benchmark_n_sample=5,
            configurable_max_combinations=True,
            configurable_workers=True,
            manual_control=True,
        ),
    ]


def get_preset(name: str, cpu_count: Optional[int] = None) -> OptimizationPreset:
    presets = get_optimization_presets(cpu_count)
    by_name = {preset.name: preset for preset in presets}
    return by_name.get(name) or by_name[CUSTOM_PRESET_NAME]


def preset_names(cpu_count: Optional[int] = None) -> list[str]:
    return [preset.name for preset in get_optimization_presets(cpu_count)]


def is_quick_preset(name: str) -> bool:
    return name == QUICK_PRESET_NAME
