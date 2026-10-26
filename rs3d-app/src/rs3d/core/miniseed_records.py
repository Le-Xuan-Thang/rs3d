"""Read just enough of miniSEED records to pick, copy and merge them without decoding any samples.

The Shake's day files are runs of fixed-length records (usually 512 bytes) in time order. Each record starts with a
48-byte fixed header that holds the start time; blockette 1000 holds the record length.
"""

from __future__ import annotations

import calendar
import struct
from typing import Protocol

HEADER = 48
MIN_YEAR, MAX_YEAR = 1990, 2100


class RecordError(ValueError):
    """The bytes do not look like a run of fixed-length miniSEED records."""


class Reader(Protocol):
    def seek(self, offset: int) -> object: ...
    def read(self, size: int) -> bytes: ...


def _endian(header: bytes) -> str:
    for order in (">", "<"):
        year = struct.unpack(order + "H", header[20:22])[0]
        if MIN_YEAR <= year <= MAX_YEAR:
            return order
    raise RecordError("not a miniSEED record (bad year)")


def start_time(header: bytes) -> float:
    """Epoch seconds of the first sample of the record whose first bytes are `header` (at least 30)."""
    if len(header) < 30:
        raise RecordError("short record header")
    order = _endian(header)
    year, doy, hour, minute, sec, _, fract = struct.unpack(order + "HHBBBBH", header[20:30])
    if not 1 <= doy <= 366 or hour > 23 or minute > 59 or sec > 60:
        raise RecordError("not a miniSEED record (bad time)")
    return calendar.timegm((year, 1, 1, 0, 0, 0)) + (doy - 1) * 86400 + hour * 3600 + minute * 60 + sec + fract * 1e-4


def sample_rate(header: bytes) -> float:
    order = _endian(header)
    factor, mult = struct.unpack(order + "hh", header[32:36])
    if factor == 0 or mult == 0:
        return 0.0
    rate = float(factor) if factor > 0 else -1.0 / factor
    return rate * mult if mult > 0 else rate / -mult


def sample_count(header: bytes) -> int:
    return struct.unpack(_endian(header) + "H", header[30:32])[0]


def end_time(header: bytes) -> float:
    """Time just after the last sample of the record."""
    rate = sample_rate(header)
    return start_time(header) + (sample_count(header) / rate if rate else 0.0)


def record_length(first: bytes) -> int:
    """Record length in bytes from blockette 1000 of the first record (needs at least 64 bytes of it)."""
    order = _endian(first)
    n_blockettes, = struct.unpack("B", first[39:40])
    offset, = struct.unpack(order + "H", first[46:48])
    for _ in range(max(n_blockettes, 0)):
        if offset < HEADER or offset + 8 > len(first):
            break
        kind, nxt = struct.unpack(order + "HH", first[offset:offset + 4])
        if kind == 1000:
            exponent = first[offset + 6]
            if 8 <= exponent <= 20:
                return 1 << exponent
            break
        if nxt == 0:
            break
        offset = nxt
    raise RecordError("no blockette 1000: record length unknown")


def split_records(data: bytes, length: int) -> list[bytes]:
    return [data[i:i + length] for i in range(0, len(data) - length + 1, length)]


def merge_records(existing: bytes, new: bytes, length: int) -> bytes:
    """Union of two runs of records, sorted by start time; a record present in both is kept once."""
    by_start: dict[float, bytes] = {}
    for rec in split_records(existing, length) + split_records(new, length):
        by_start[round(start_time(rec[:HEADER]), 4)] = rec
    return b"".join(by_start[t] for t in sorted(by_start))


def _first_at_or_after(reader: Reader, n: int, length: int, t: float) -> int:
    """Index of the first record that starts at or after `t` (n if none): binary search over time-ordered records."""
    lo, hi = 0, n
    while lo < hi:
        mid = (lo + hi) // 2
        reader.seek(mid * length)
        if start_time(reader.read(HEADER)) < t:
            lo = mid + 1
        else:
            hi = mid
    return lo


def read_range(reader: Reader, size: int, start: float, end: float, pad: int = 4) -> tuple[bytes, float, int]:
    """The records of a remote day file that cover [start, end].

    Returns (records, data_end, record_length). `data_end` is when the last record in the whole file ends, so the
    caller knows how far the file has grown. `pad` extra records on each side catch a record that begins just before
    `start`. Raises RecordError when the file is not a run of fixed-length records.
    """
    reader.seek(0)
    first = reader.read(64)
    length = record_length(first)
    n = size // length
    if n == 0:
        return b"", 0.0, length
    reader.seek((n - 1) * length)
    data_end = end_time(reader.read(HEADER))
    i0 = max(0, _first_at_or_after(reader, n, length, start) - pad)
    i1 = min(n, _first_at_or_after(reader, n, length, end) + pad)
    reader.seek(i0 * length)
    chunks, remaining = [], (i1 - i0) * length
    while remaining > 0:
        part = reader.read(min(remaining, 1 << 20))
        if not part:
            break
        chunks.append(part)
        remaining -= len(part)
    return b"".join(chunks), data_end, length
