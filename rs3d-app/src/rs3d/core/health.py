"""Data health of a loaded selection: how much of the range is covered, and where the gaps are."""

from __future__ import annotations

from dataclasses import dataclass

from obspy import Stream, UTCDateTime


@dataclass(frozen=True)
class Health:
    completeness: float  # 0..1, share of the range with data on every channel
    gaps: list[tuple[UTCDateTime, UTCDateTime]]  # periods where at least one channel has no data


def _merge(spans: list[tuple[float, float, float]]) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for s, e, delta in sorted(spans):
        if merged and s - merged[-1][1] <= 0.5 * delta:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def _missing(spans: list[tuple[float, float]], start: float, end: float) -> list[tuple[float, float]]:
    out, pos = [], start
    for s, e in spans:
        if s > pos:
            out.append((pos, min(s, end)))
        pos = max(pos, e)
        if pos >= end:
            break
    if pos < end:
        out.append((pos, end))
    return out


def health(st: Stream, start: UTCDateTime, end: UTCDateTime) -> Health:
    a, b = start.timestamp, end.timestamp
    per_channel: dict[str, list[tuple[float, float, float]]] = {}
    for tr in st:
        delta = tr.stats.delta
        s, e = tr.stats.starttime.timestamp, tr.stats.endtime.timestamp + delta
        if e > a and s < b:
            per_channel.setdefault(tr.stats.channel, []).append((max(s, a), min(e, b), delta))
    if not per_channel:
        return Health(0.0, [(start, end)])
    holes = sorted(h for spans in per_channel.values() for h in _missing(_merge(spans), a, b))
    gaps: list[tuple[float, float]] = []
    for s, e in holes:
        if gaps and s <= gaps[-1][1]:
            gaps[-1] = (gaps[-1][0], max(gaps[-1][1], e))
        else:
            gaps.append((s, e))
    missing = sum(e - s for s, e in gaps)
    return Health(1.0 - missing / (b - a), [(UTCDateTime(s), UTCDateTime(e)) for s, e in gaps])
