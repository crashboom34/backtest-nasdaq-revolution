"""
gate_v_exposure_sources.py — AF-V-07 Slice E3-B1 : primitive d'intervalles UTC demi-ouverts.

Contrat normatif : ADR 0025 Décision 23, 23.3 (fenêtres semi-ouvertes `[start, end)`), 23.27/23.28 (instants UTC normalisés à
six décimales, recouvrement `a.start < b.end ET b.start < a.end`) et 23.29 (design E3-B).

Module PUR : aucune entrée/sortie, aucune horloge, aucun état global mutable, aucune donnée de marché, aucun registre, aucun
moteur. Il ne retourne que des FAITS de géométrie temporelle ; il ne dit jamais FRESH ni « exposé » (c'est le rôle des couches
supérieures). Instants : chaînes avec décalage explicite (`Z` ou `±HH:MM`), normalisées par `normalize_utc_instant` d'E3-A
(API publique) en `YYYY-MM-DDTHH:MM:SS.ffffffZ`. Jamais de comparaison lexicale de chaînes non normalisées, jamais d'heure
locale implicite.

Erreurs : `TypeError` pour un argument qui n'est pas exactement un `str` ; `ValueError` pour une valeur invalide (instant naïf ou
mal formé, fenêtre vide ou inversée, dépassement de la borne maximale représentable).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from gate_v_final_holdout_protocol import OverlapVerdict, normalize_utc_instant


def _parse_normalized(instant: str) -> datetime:
    """Parse une chaîne DÉJÀ normalisée (`...ffffffZ`) en datetime aware UTC."""
    return datetime.fromisoformat(instant[:-1] + "+00:00")


def _format_normalized(moment: datetime) -> str:
    """Formate un datetime aware UTC en `YYYY-MM-DDTHH:MM:SS.ffffffZ` (champs explicites : indépendant de la plateforme)."""
    return (
        f"{moment.year:04d}-{moment.month:02d}-{moment.day:02d}"
        f"T{moment.hour:02d}:{moment.minute:02d}:{moment.second:02d}.{moment.microsecond:06d}Z"
    )


def _ensure_exact_str(*values: object) -> None:
    """Contrôle de type préalable : `TypeError` prime sur toute `ValueError`, quel que soit l'ordre des arguments."""
    for value in values:
        if type(value) is not str:
            raise TypeError(f"instant must be exactly a str, got {type(value).__name__}")


def normalize_window(start_utc: str, end_utc: str) -> tuple[str, str]:
    """Normalise les deux bornes d'une fenêtre demi-ouverte `[start, end)` ; exige `start < end` (instants UTC)."""
    _ensure_exact_str(start_utc, end_utc)
    start = normalize_utc_instant(start_utc)
    end = normalize_utc_instant(end_utc)
    if not _parse_normalized(start) < _parse_normalized(end):
        raise ValueError("window must satisfy start < end (half-open [start, end))")
    return start, end


def windows_overlap(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    """Vrai si les fenêtres demi-ouvertes `[a_start, a_end)` et `[b_start, b_end)` se recoupent.

    Formule normative : `a.start < b.end ET b.start < a.end`. Fenêtres adjacentes : pas de recouvrement ; une intersection
    d'une microseconde recoupe ; symétrique ; indépendant de la représentation du décalage. Les quatre bornes sont validées
    (cf. `normalize_window`) avant toute comparaison, sur des datetimes (jamais lexicalement).
    """
    _ensure_exact_str(a_start, a_end, b_start, b_end)
    a_start_n, a_end_n = normalize_window(a_start, a_end)
    b_start_n, b_end_n = normalize_window(b_start, b_end)
    return _parse_normalized(a_start_n) < _parse_normalized(b_end_n) and _parse_normalized(b_start_n) < _parse_normalized(a_end_n)


def overlap_verdict(a_start: str, a_end: str, b_start: str, b_end: str) -> OverlapVerdict:
    """Verdict de recouvrement `OVERLAPS` ou `NO_OVERLAP` ; jamais `UNKNOWN` (toute entrée invalide lève, cf. `windows_overlap`)."""
    if windows_overlap(a_start, a_end, b_start, b_end):
        return OverlapVerdict.OVERLAPS
    return OverlapVerdict.NO_OVERLAP


def inclusive_end_to_exclusive(end_inclusive: str) -> str:
    """Convertit une fin INCLUSIVE legacy en fin exclusive : `end_inclusive + 1µs`, normalisée UTC.

    À n'appliquer que lorsque la sémantique inclusive de la source est ÉTABLIE (jamais aux plans, Claims, réservations ni aux
    intervalles déjà demi-ouverts) : la détection de la source legacy relève de B3, pas de cette primitive. Fail closed :
    au-delà de la borne maximale représentable (`9999-12-31T23:59:59.999999Z`) → `ValueError` (jamais d'arrondi, de troncature
    ni d'infini).
    """
    _ensure_exact_str(end_inclusive)
    end = _parse_normalized(normalize_utc_instant(end_inclusive))
    try:
        exclusive = end + timedelta(microseconds=1)
    except OverflowError:
        raise ValueError("inclusive end + 1µs exceeds the maximum representable UTC instant") from None
    return _format_normalized(exclusive)


def inclusive_window_to_half_open(start_utc: str, end_inclusive_utc: str) -> tuple[str, str]:
    """Convertit `[start, end_inclusive]` en `[start, end_inclusive + 1µs)` ; exige `start <= end_inclusive` (donc fenêtre non vide)."""
    _ensure_exact_str(start_utc, end_inclusive_utc)
    start = normalize_utc_instant(start_utc)
    end_inclusive = normalize_utc_instant(end_inclusive_utc)
    if _parse_normalized(end_inclusive) < _parse_normalized(start):
        raise ValueError("inclusive window must satisfy start <= end_inclusive")
    return start, inclusive_end_to_exclusive(end_inclusive)
