"""Business time and technical time (UC1-BUILD-SPEC 3.2).

* Business time ``demo_now()`` = date ``GPOS_DEMO_DATE`` + the current wall-clock
  time in ``GPOS_TZ``. It drives prices, validities, sales windows, seasons, ``ref30``,
  ids (``YYMMDD``), loyalty purchases and every date shown in a text.
* Technical time ``real_now()`` (UTC) drives event headers, staleness guards,
  latencies, watchdogs and the ``ts`` of our own events.

Windows over past data end yesterday: ``past_window(D, n)`` = ``[D-n, D-1]``, both
edges inclusive; booth purchases always carry business date ``D`` and so never count.

The proto JSON helpers build ``datatype.Timestamp`` / ``datatype.OffsetTimestamp``
(GEBIT style ``{seconds, nanos[, offset]}``, int64 as a JSON string). They are not
``google.protobuf.Timestamp``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .config import Settings

DEFAULT_TZ = "Europe/Berlin"


def real_now() -> datetime:
    """Technical time: timezone-aware ``datetime`` in UTC."""
    return datetime.now(UTC)


def demo_now(s: Settings, now: datetime | None = None) -> datetime:
    """Business time: ``GPOS_DEMO_DATE`` with the current wall-clock time in ``GPOS_TZ``.

    ``now`` (aware) replaces the real clock, for tests.
    """
    zone = ZoneInfo(s.tz)
    local = (now or real_now()).astimezone(zone)
    return datetime.combine(s.demo_date, local.time(), tzinfo=zone)


def demo_today(s: Settings) -> date:
    """Business date ``D`` (= ``GPOS_DEMO_DATE``)."""
    return s.demo_date


def demo_at(s: Settings, day: date, hour: int = 0, minute: int = 0) -> datetime:
    """Business date ``day`` at ``hour:minute`` local time in ``GPOS_TZ`` (aware)."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZoneInfo(s.tz))


def past_window(today: date, days: int) -> tuple[date, date]:
    """``[today - days, today - 1]``, both edges inclusive (e.g. 56 days = 8 weeks)."""
    if days < 1:
        raise ValueError(f"window needs at least one day, got {days}")
    return today - timedelta(days=days), today - timedelta(days=1)


def in_window(day: date, window: tuple[date, date]) -> bool:
    """True when ``day`` lies in the inclusive ``window``."""
    return window[0] <= day <= window[1]


def iso_ts(value: datetime | None = None, tz: str = DEFAULT_TZ) -> str:
    """ISO-8601 with milliseconds and offset in ``tz``: ``2026-11-11T14:20:01.412+01:00``.

    Default value is the technical time; used for ``ts`` of our own events (7.2).
    """
    return (value or real_now()).astimezone(ZoneInfo(tz)).isoformat(timespec="milliseconds")


def ts_json(value: datetime) -> dict[str, Any]:
    """``datatype.Timestamp`` as proto3 JSON: ``{"seconds": "…", "nanos": n}``.

    ``nanos`` is left out when zero, as ``MessageToDict`` does.
    """
    if value.tzinfo is None:
        raise ValueError("timestamp needs an aware datetime")
    epoch_us = round(value.timestamp() * 1_000_000)
    seconds, micros = divmod(epoch_us, 1_000_000)
    out: dict[str, Any] = {"seconds": str(seconds)}
    if micros:
        out["nanos"] = micros * 1000
    return out


def offset_ts_json(value: datetime) -> dict[str, Any]:
    """``datatype.OffsetTimestamp`` as proto3 JSON, offset to UTC in minutes.

    ``demo_at(s, date(2027, 2, 23), 20)`` -> ``{"seconds": "1803409200", "offset": 60}``.
    """
    offset = value.utcoffset()
    if offset is None:
        raise ValueError("offset timestamp needs an aware datetime")
    return {**ts_json(value), "offset": int(offset.total_seconds() // 60)}


def from_ts(obj: Mapping[str, Any] | Any, tz: str | None = None) -> datetime:
    """Inverse of :func:`ts_json` / :func:`offset_ts_json` for a dict or a message.

    The result is aware: in the stored ``offset`` when present, else in ``tz``
    (default UTC).
    """
    if isinstance(obj, Mapping):
        seconds = int(obj.get("seconds", 0) or 0)
        nanos = int(obj.get("nanos", 0) or 0)
        offset = obj.get("offset")
    else:
        seconds, nanos = int(obj.seconds), int(obj.nanos)
        offset = getattr(obj, "offset", None)
    value = datetime.fromtimestamp(seconds, UTC) + timedelta(microseconds=nanos // 1000)
    if offset:
        return value.astimezone(timezone(timedelta(minutes=int(offset))))
    return value.astimezone(ZoneInfo(tz)) if tz else value
