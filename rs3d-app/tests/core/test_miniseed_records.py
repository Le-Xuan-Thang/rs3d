import io

import numpy as np
import pytest
from obspy import Trace, UTCDateTime, read

from rs3d.core.miniseed_records import (RecordError, end_time, merge_records, read_range, record_length,
                                        split_records, start_time)

T0 = UTCDateTime("2026-10-12T00:00:00")


def day_bytes(seconds=3600, reclen=512, seed=0, start=T0):
    data = np.random.default_rng(seed).integers(-3000, 3000, int(seconds * 100)).astype("int32")
    tr = Trace(data, dict(network="AM", station="R77A7", location="00", channel="EHZ", sampling_rate=100.0,
                          starttime=start))
    buf = io.BytesIO()
    tr.write(buf, format="MSEED", reclen=reclen, encoding="STEIM2")
    return buf.getvalue()


def test_header_fields():
    raw = day_bytes()
    assert record_length(raw[:64]) == 512
    assert start_time(raw[:48]) == T0.timestamp
    recs = split_records(raw, 512)
    assert abs(end_time(recs[-1][:48]) - (T0 + 3600).timestamp) < 0.02
    assert record_length(day_bytes(60, reclen=4096)[:64]) == 4096


def test_read_range_returns_only_the_records_around_the_range():
    raw = day_bytes()
    got, data_end, length = read_range(io.BytesIO(raw), len(raw), (T0 + 1800).timestamp, (T0 + 1860).timestamp)
    assert length == 512 and abs(data_end - (T0 + 3600).timestamp) < 0.02
    assert len(got) < len(raw) / 20 and len(got) % 512 == 0
    tr = read(io.BytesIO(got))[0]
    assert tr.stats.starttime <= T0 + 1800 and tr.stats.endtime >= T0 + 1860 - 0.02
    whole = read(io.BytesIO(raw))[0].slice(T0 + 1800, T0 + 1860)
    assert np.array_equal(tr.slice(T0 + 1800, T0 + 1860).data, whole.data)


def test_read_range_at_the_edges_and_outside():
    raw = day_bytes(600)
    head, _, _ = read_range(io.BytesIO(raw), len(raw), T0.timestamp, (T0 + 10).timestamp)
    assert read(io.BytesIO(head))[0].stats.starttime == T0
    tail, _, _ = read_range(io.BytesIO(raw), len(raw), (T0 + 590).timestamp, (T0 + 9999).timestamp)
    assert abs(read(io.BytesIO(tail))[0].stats.endtime - (T0 + 600 - 0.01)) < 0.02
    nothing, _, _ = read_range(io.BytesIO(raw), len(raw), (T0 + 9000).timestamp, (T0 + 9100).timestamp)
    assert len(nothing) <= 4 * 512


def test_merge_keeps_each_record_once_in_time_order():
    raw = day_bytes(600)
    a, _, _ = read_range(io.BytesIO(raw), len(raw), (T0 + 100).timestamp, (T0 + 200).timestamp)
    b, _, _ = read_range(io.BytesIO(raw), len(raw), (T0 + 150).timestamp, (T0 + 300).timestamp)
    merged = merge_records(a, b, 512)
    st = read(io.BytesIO(merged))
    assert len(st) == 1 and st[0].stats.starttime <= T0 + 100 and st[0].stats.endtime >= T0 + 300 - 0.02
    assert merge_records(merged, a, 512) == merged


def test_not_miniseed_is_refused():
    with pytest.raises(RecordError):
        record_length(b"\x00" * 64)
    with pytest.raises(RecordError):
        read_range(io.BytesIO(b"x" * 4096), 4096, 0, 1)
