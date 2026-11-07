"""Datas: gravadas em UTC no banco e mostradas no fuso America/Sao_Paulo."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from .config import FUSO


def agora() -> datetime:
    return datetime.now(timezone.utc)


def utc(dt: datetime | None) -> datetime | None:
    """O SQLite devolve datas sem fuso; elas foram gravadas em UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def formatar(dt: datetime | None) -> str:
    """'07/11/2026 10:42' no horário de Brasília."""
    dt = utc(dt)
    return dt.astimezone(FUSO).strftime("%d/%m/%Y %H:%M") if dt else ""


def iso(dt: datetime | None) -> str | None:
    dt = utc(dt)
    return dt.astimezone(FUSO).isoformat(timespec="seconds") if dt else None


def inicio_do_dia(d: date) -> datetime:
    """00:00 do dia em Brasília, convertido para UTC."""
    return datetime.combine(d, time.min, tzinfo=FUSO).astimezone(timezone.utc)


def fim_do_dia(d: date) -> datetime:
    """Último instante do dia em Brasília (exclusivo: 00:00 do dia seguinte), em UTC."""
    return inicio_do_dia(d + timedelta(days=1))
