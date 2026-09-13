"""
strategy_contracts.py — Contrats déclaratifs partagés entre stratégies et protocole (moteur
d'optimisation) — State/Session Readiness V1 (2026-09-14).

Module **leaf** volontairement isolé : aucune dépendance vers `engine.py`/`optimizer.py`
(évite tout import circulaire — `strategies/perfect_revolution_v1.py` ET `optimizer.py`
l'importent, jamais l'inverse). Même esprit que `atomic_json_store.py`/`path_resolver.py`.

**Problème corrigé** : une stratégie daily-stateful (ex. Perfect Revolution) construit un état
INFORMATIONAL (ex. Opening Range) exclusivement dans `on_bar()`, jamais rejoué avant le début
d'une fenêtre d'évaluation (`loop_start`). Une frontière TRAIN/TEST exacte (Dette B, DONE) peut
tomber n'importe où dans la journée, y compris pendant ou après cette fenêtre horaire — coupant
silencieusement l'état informational nécessaire à la première décision (prouvé empiriquement,
audit précédent : `_or_ready` reste `False` toute la journée, ou l'Opening Range calculé est
silencieusement faux).

**Architecture retenue (READY-3, `/codebase-design`)** : la stratégie DÉCLARE une contrainte
minimale (`state_readiness(params) -> DailyStateReadiness`), le protocole (`optimizer.py`)
RÉSOUT la frontière effective (`resolve_state_ready_boundary()`) — jamais l'inverse. `engine.py`
reste totalement ignorant de cette notion (aucune modification). Mirror exact du précédent déjà
établi par `Strategy.required_warmup(params)` (Dette WARMUP dynamique, DONE) : `hasattr()` +
fallback côté appelant, `@staticmethod` côté stratégie.

**Règle V1, volontairement simple (aucun calendrier de marché, aucun replay de `on_bar()`)** :
la frontière demandée, convertie en heure locale (fuseau déclaré), est déjà admissible si son
heure est `<= latest_safe_start_hour:minute` (comparaison INCLUSIVE) ; sinon elle est décalée au
**minuit local du jour calendaire suivant** — construction DST-safe (date locale + 1 jour, PUIS
relocalisation ; jamais `+ Timedelta(hours=24)`, qui produit un décalage d'une heure les jours de
changement d'heure, vérifié empiriquement). Aucune notion de "jour de marché" : une frontière
tombant un week-end est parfaitement acceptée — le moteur démarrera à la première barre
réellement disponible >= cette frontière, aucune donnée n'est perdue (la qualité/complétude des
données reste hors scope, voir Data Center / data quality).

**État EXECUTION (compteurs, PnL, système on/off) volontairement HORS scope de ce module** :
déjà correctement traité par l'existant (reset automatique sur nouvelle journée + instance
`Strategy()` fraîche par backtest, aucune fuite TRAIN→TEST — confirmé par audit). Ce module ne
résout QUE la readiness de l'état INFORMATIONAL, jamais un ajustement lié à l'exécution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time, timedelta
from typing import Optional

import pandas as pd


@dataclass(frozen=True)
class DailyStateReadiness:
    """Déclaration minimale d'une stratégie daily-stateful : elle a besoin que toutes les
    barres locales du jour courant, jusqu'à `latest_safe_start_hour:latest_safe_start_minute`
    inclus, soient disponibles pour reconstruire son état informational (ex. Opening Range)
    avant sa première décision. Interprétée uniquement par `resolve_state_ready_boundary()` —
    jamais par `engine.py`, qui reste ignorant de cette notion.

    `timezone` : fuseau dans lequel `latest_safe_start_hour`/`latest_safe_start_minute`
    s'interprètent (Europe/Paris pour Perfect Revolution — une future stratégie sur un autre
    marché déclarerait son propre fuseau)."""

    latest_safe_start_hour: int
    latest_safe_start_minute: int
    timezone: str = "Europe/Paris"


@dataclass(frozen=True)
class StateReadinessResolution:
    """Résultat de `resolve_state_ready_boundary()` — conserve `requested_boundary` (jamais
    écrasée) et `effective_boundary` (celle réellement utilisée) distinctement, pour une
    reproductibilité auditable. `adjusted` indique si un décalage a réellement eu lieu (`False`
    quand `requested_boundary == effective_boundary`, y compris quand aucune déclaration
    readiness n'existe)."""

    requested_boundary: str
    effective_boundary: str
    adjusted: bool


def _parse_local(value, tz: str) -> pd.Timestamp:
    """Convertit `value` (chaîne naïve, ISO+offset, ou `pd.Timestamp` déjà tz-aware) vers un
    `pd.Timestamp` dans `tz` — même logique que `engine._parse_boundary_timestamp()`, dupliquée
    ici volontairement : `strategy_contracts.py` est un module leaf, il ne doit dépendre
    d'aucune couche supérieure (`engine.py`), voir docstring du module."""
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize(tz)
    return ts.tz_convert(tz)


def resolve_state_ready_boundary(
    requested_boundary: str,
    readiness_spec: Optional[DailyStateReadiness],
) -> StateReadinessResolution:
    """Fonction PURE — aucun DataFrame nécessaire pour cette V1 (règle purement horaire,
    déterministe). `readiness_spec=None` (stratégie stateless, ou sans contrat déclaré) :
    aucun ajustement, `effective_boundary == requested_boundary`, `adjusted=False`.

    Sinon : si l'heure locale (fuseau `readiness_spec.timezone`) de `requested_boundary` est
    `<= latest_safe_start_hour:minute` (inclusif), la frontière est déjà admissible — inchangée.
    Sinon, décalée au minuit local du jour calendaire suivant (DST-safe : date locale + 1 jour,
    puis relocalisation — jamais une arithmétique d'heures brute)."""
    if readiness_spec is None:
        return StateReadinessResolution(
            requested_boundary=requested_boundary,
            effective_boundary=requested_boundary,
            adjusted=False,
        )

    local_ts = _parse_local(requested_boundary, readiness_spec.timezone)
    cutoff = time(readiness_spec.latest_safe_start_hour, readiness_spec.latest_safe_start_minute)

    if local_ts.time() <= cutoff:
        return StateReadinessResolution(
            requested_boundary=requested_boundary,
            effective_boundary=requested_boundary,
            adjusted=False,
        )

    next_local_date = local_ts.date() + timedelta(days=1)
    effective_ts = pd.Timestamp(next_local_date, tz=readiness_spec.timezone)
    return StateReadinessResolution(
        requested_boundary=requested_boundary,
        effective_boundary=effective_ts.isoformat(),
        adjusted=True,
    )
