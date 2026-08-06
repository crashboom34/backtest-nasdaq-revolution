"""
market_data/eodhd/calendar.py — Calendrier de marché structuré à partir de EodhdClient.get_exchange_details().

Format brut confirmé via le MCP EODHD le 2026-08-06 (exchange "US", voir AI_HANDOFF.md) :
{Code, Timezone, TradingHours: {Open, Close, OpenUTC, CloseUTC, WorkingDays}, ExchangeHolidays:
{"0": {Holiday, Date, Type}, ...}, ExchangeEarlyCloseDays: {"0": {..., EarlyClose}, ...},
isOpen}. Ce module ne fait aucun appel réseau : il transforme une réponse déjà obtenue via
EodhdClient.get_exchange_details() en structure exploitable par le reste du code (resample,
quality, UI).

Portée volontairement limitée à cette étape : jours fériés + heures de séance régulière +
fermetures anticipées. Pas encore de pré-marché/after-hours (EODHD "v2" documente ces sessions
mais leur format exact n'a pas été vérifié en conditions réelles à cette étape — voir
AI_HANDOFF.md, pas de champ deviné).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class ExchangeCalendar:
    """Calendrier de marché structuré pour une place de marché EODHD."""

    exchange_code: str
    timezone: str
    open_utc: str = ""
    close_utc: str = ""
    working_days: tuple = ()
    holidays: tuple = field(default_factory=tuple)
    early_close_days: tuple = field(default_factory=tuple)
    is_open_now: bool = False


def _parse_date(value: str):
    return datetime.strptime(value, "%Y-%m-%d").date()


def parse_exchange_calendar(raw: dict) -> ExchangeCalendar:
    """Transforme la réponse brute de EodhdClient.get_exchange_details() en ExchangeCalendar.

    Tolérant aux champs optionnels absents (jamais d'exception pour un champ manquant) — seul
    "Code" est utilisé tel quel s'il existe, sinon chaîne vide.
    """
    trading_hours = raw.get("TradingHours") or {}
    working_days_raw = trading_hours.get("WorkingDays") or ""
    working_days = tuple(d.strip() for d in working_days_raw.split(",") if d.strip())

    holidays = tuple(
        _parse_date(entry["Date"])
        for entry in (raw.get("ExchangeHolidays") or {}).values()
        if isinstance(entry, dict) and entry.get("Date")
    )
    early_close_days = tuple(
        _parse_date(entry["Date"])
        for entry in (raw.get("ExchangeEarlyCloseDays") or {}).values()
        if isinstance(entry, dict) and entry.get("Date")
    )

    return ExchangeCalendar(
        exchange_code=raw.get("Code", ""),
        timezone=raw.get("Timezone", ""),
        open_utc=trading_hours.get("OpenUTC", ""),
        close_utc=trading_hours.get("CloseUTC", ""),
        working_days=working_days,
        holidays=holidays,
        early_close_days=early_close_days,
        is_open_now=bool(raw.get("isOpen", False)),
    )


_WEEKDAY_CODES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def is_trading_day(calendar: ExchangeCalendar, day: date) -> bool:
    """True si `day` est un jour de séance : dans working_days ET pas un jour férié.

    Une fermeture anticipée (early_close_days) reste un jour de séance (la séance a lieu, juste
    plus courte) — seul un jour férié complet (holidays) exclut la séance.
    """
    if day in calendar.holidays:
        return False
    if not calendar.working_days:
        return True  # pas d'information de jours ouvrés : ne rien exclure par défaut
    weekday_code = _WEEKDAY_CODES[day.weekday()]
    return weekday_code in calendar.working_days
