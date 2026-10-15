"""Time helpers for the Data page: presets, display time zone, slider percent <-> time."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from obspy import UTCDateTime

FORMAT = "%Y-%m-%d %H:%M:%S"
PRESETS = ("last_10_min", "last_hour", "today", "yesterday", "last_7_days")


def local_offset(now: datetime | None = None) -> timedelta:
    now = now or datetime.now().astimezone()
    return now.utcoffset() or timedelta(0)


def to_text(t: UTCDateTime, use_local: bool, offset: timedelta | None = None) -> str:
    dt = t.datetime
    if use_local:
        dt += offset if offset is not None else local_offset()
    return dt.strftime(FORMAT)


def from_text(text: str, use_local: bool, offset: timedelta | None = None) -> UTCDateTime:
    """Parse 'YYYY-MM-DD hh:mm:ss' typed in the display zone; raises ValueError if malformed."""
    dt = datetime.strptime(text.strip(), FORMAT)
    if use_local:
        dt -= offset if offset is not None else local_offset()
    return UTCDateTime(dt.replace(tzinfo=timezone.utc))


def preset_range(name: str, now: UTCDateTime, use_local: bool,
                 offset: timedelta | None = None) -> tuple[UTCDateTime, UTCDateTime]:
    """(start, end) in UTC. 'today'/'yesterday' follow the displayed time zone."""
    now = UTCDateTime(int(now.timestamp))  # whole seconds
    if name == "last_10_min":
        return now - 600, now
    if name == "last_hour":
        return now - 3600, now
    if name == "last_7_days":
        return now - 7 * 86400, now
    shift = (offset if offset is not None else local_offset()).total_seconds() if use_local else 0.0
    local_now = now + shift
    midnight = UTCDateTime(local_now.year, local_now.month, local_now.day) - shift
    if name == "today":
        return midnight, now
    if name == "yesterday":
        return midnight - 86400, midnight
    raise ValueError(f"unknown preset {name!r}")


def view_range(level: str, center: UTCDateTime) -> tuple[UTCDateTime, UTCDateTime]:
    """Visible span of the coverage bar for zoom level week | day | hour, in UTC."""
    if level == "hour":
        start = UTCDateTime(center.year, center.month, center.day, center.hour)
        return start, start + 3600
    day = UTCDateTime(center.year, center.month, center.day)
    if level == "day":
        return day, day + 86400
    if level == "week":
        return day - 6 * 86400, day + 86400
    raise ValueError(f"unknown zoom level {level!r}")


def shift_view(level: str, start: UTCDateTime, direction: int) -> UTCDateTime:
    """New center after ◀ (-1) or ▶ (+1)."""
    step = {"hour": 3600, "day": 86400, "week": 7 * 86400}[level]
    return start + direction * step + step / 2


def percent_to_time(view: tuple[UTCDateTime, UTCDateTime], percent: float) -> UTCDateTime:
    a, b = view
    return UTCDateTime(int((a + (b - a) * max(0.0, min(100.0, percent)) / 100).timestamp))
