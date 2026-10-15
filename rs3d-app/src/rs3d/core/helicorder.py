"""Helicorder data: one channel of one UTC day as rows of 30 minutes, reduced to min/max pairs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
from obspy import Inventory, Stream, UTCDateTime

from rs3d.core.export import process
from rs3d.core.live import minmax_decimate
from rs3d.core.models import Selection
from rs3d.core.store import Store

ROW_MINUTES = 30
POINTS_PER_ROW = 3000
MIN_SPAN = 5.0      # seconds: smallest detail window
MAX_SPAN = 3600.0   # seconds: largest detail window


@dataclass(frozen=True)
class Row:
    start: UTCDateTime
    seconds: np.ndarray  # offsets from `start`
    values: np.ndarray   # NaN marks a gap


def process_safe(st: Stream, sel: Selection, inventory: Inventory | None) -> Stream:
    """export.process with a clear error when m/s is asked for without an instrument response.

    Other errors (for example a response that does not match the channel) are not swallowed.
    """
    if sel.units == "m/s" and inventory is None:
        raise ValueError("units 'm/s' need an instrument response (inventory)")
    return process(st, sel, inventory)


def load_window(store: Store, net: str, sta: str, loc: str, channel: str, start: UTCDateTime, end: UTCDateTime,
                units: str = "counts", band: tuple[float, float] | None = None,
                inventory: Inventory | None = None) -> Stream:
    sel = Selection(net, sta, loc, start, end, channels=(channel,), filter=band, units=units)
    return process_safe(store.load(sel), sel, inventory)


def load_day(store: Store, net: str, sta: str, loc: str, channel: str, day: date, units: str = "counts",
             band: tuple[float, float] | None = None, inventory: Inventory | None = None) -> Stream:
    start = UTCDateTime(day.year, day.month, day.day)
    return load_window(store, net, sta, loc, channel, start, start + 86400, units, band, inventory)


def build_rows(st: Stream, day_start: UTCDateTime, row_minutes: int = ROW_MINUTES,
               points: int = POINTS_PER_ROW) -> list[Row]:
    span = row_minutes * 60
    rows: list[Row] = []
    for i in range(24 * 60 // row_minutes):
        a = day_start + i * span
        t_parts: list[np.ndarray] = []
        v_parts: list[np.ndarray] = []
        for tr in sorted(st.slice(a, a + span - 1e-6), key=lambda x: x.stats.starttime):
            delta = tr.stats.delta
            t = (tr.stats.starttime - a) + np.arange(tr.stats.npts) * delta
            if t_parts and t[0] - t_parts[-1][-1] > 1.5 * delta:
                t_parts.append(np.array([t[0] - 0.5 * delta]))
                v_parts.append(np.array([np.nan]))
            t_parts.append(t)
            v_parts.append(tr.data.astype(float))
        if not t_parts:
            rows.append(Row(a, np.array([]), np.array([])))
            continue
        t, v = np.concatenate(t_parts), np.concatenate(v_parts)
        finite = v[np.isfinite(v)]
        if finite.size:  # raw counts sit on a DC offset: show the signal, not the offset
            v = v - np.median(finite)
        if len(t) > points:
            t, v = minmax_decimate(t, v, points)
        rows.append(Row(a, t, v))
    return rows


def scale_for(rows: list[Row], factor: float = 1.0) -> float:
    """Amplitude that maps to one row height, shared by all rows. A single huge event does not flatten the day."""
    parts = [np.abs(r.values[np.isfinite(r.values)]) for r in rows if len(r.values)]
    values = np.concatenate(parts) if parts else np.array([])
    if values.size == 0:
        return 1.0
    base = 2.0 * float(np.percentile(values, 99))
    return (base or 1.0) / factor


def click_to_time(day_start: UTCDateTime, row_minutes: int, row_index: int, x_fraction: float) -> UTCDateTime:
    span = row_minutes * 60
    return day_start + row_index * span + min(max(x_fraction, 0.0), 1.0) * span


def zoom_window(start: UTCDateTime, end: UTCDateTime, factor: float) -> tuple[UTCDateTime, UTCDateTime]:
    """Same centre, span multiplied by `factor` (2 = zoom out), clamped to [MIN_SPAN, MAX_SPAN]."""
    centre = (start.timestamp + end.timestamp) / 2
    span = min(max((end - start) * factor, MIN_SPAN), MAX_SPAN)
    return UTCDateTime(centre - span / 2), UTCDateTime(centre + span / 2)


def shift_window(start: UTCDateTime, end: UTCDateTime, direction: int) -> tuple[UTCDateTime, UTCDateTime]:
    step = (end - start) / 2 * direction
    return start + step, end + step
