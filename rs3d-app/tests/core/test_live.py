import threading

import numpy as np
from obspy import Trace, UTCDateTime

from rs3d.core.live import BACKOFF, LiveStream, RingBuffer

T0 = UTCDateTime("2026-10-12T12:00:00")


def trace(channel, start, n, rate=100.0, value=1.0):
    return Trace(np.full(n, value), header={"channel": channel, "starttime": start, "sampling_rate": rate})


def test_contiguous_packets_merge():
    buf = RingBuffer()
    buf.add(trace("EHZ", T0, 100))
    buf.add(trace("EHZ", T0 + 1, 100))
    t, v = buf.snapshot("EHZ", 10)
    assert len(t) == 200 and not np.isnan(v).any()
    assert buf.latest() == (T0 + 2).timestamp


def test_gap_is_marked_with_nan():
    buf = RingBuffer()
    buf.add(trace("EHZ", T0, 100))
    buf.add(trace("EHZ", T0 + 5, 100))
    t, v = buf.snapshot("EHZ", 10)
    assert np.isnan(v).sum() == 1 and len(t) == 201


def test_old_data_is_dropped():
    buf = RingBuffer(seconds=60)
    buf.add(trace("EHZ", T0, 100))
    buf.add(trace("EHZ", T0 + 120, 100))
    t, _ = buf.snapshot("EHZ", 600)
    assert t.min() >= (T0 + 120).timestamp


def test_snapshot_window_and_unknown_channel():
    buf = RingBuffer()
    buf.add(trace("EHZ", T0, 1000))
    t, _ = buf.snapshot("EHZ", 2)
    assert len(t) == 200 and t[-1] < (T0 + 10).timestamp
    assert buf.snapshot("EHN", 2)[0].size == 0


def test_decimation_keeps_peaks():
    buf = RingBuffer()
    data = np.zeros(30000)
    data[12345] = 999.0
    buf.add(Trace(data, header={"channel": "EHZ", "starttime": T0, "sampling_rate": 100.0}))
    t, v = buf.snapshot("EHZ", 300, max_points=1000)
    assert len(t) <= 1000 and v.max() == 999.0


class FakeSource:
    def __init__(self, traces, fail=None):
        self.traces, self.fail, self.closed = traces, fail, False

    def run(self, on_trace):
        for tr in self.traces:
            on_trace(tr)
        if self.fail:
            raise self.fail

    def close(self):
        self.closed = True


def test_reconnects_with_backoff_and_resets_after_success():
    sleeps, made = [], []
    stop_after = threading.Event()

    def factory():
        n = len(made)
        if n in (0, 1):
            src = FakeSource([], fail=ConnectionRefusedError("refused"))
        elif n == 2:
            src = FakeSource([trace("EHZ", T0, 100)], fail=ConnectionResetError("cable"))
        else:
            stop_after.set()
            src = FakeSource([], fail=ConnectionRefusedError("refused"))
        made.append(src)
        return src

    live = LiveStream(factory, sleep=lambda s: sleeps.append(s))
    live.start()
    assert stop_after.wait(5)
    live.stop()
    assert sleeps[:3] == [BACKOFF[0], BACKOFF[1], BACKOFF[0]]
    assert live.buffer.snapshot("EHZ", 10)[0].size == 100
    assert live.state == "stopped"


def test_is_stale_before_any_data():
    live = LiveStream(lambda: FakeSource([]))
    assert live.is_stale()


def test_bandpass_removes_offset_and_keeps_gap():
    buf = RingBuffer()
    t = np.arange(1000) / 100.0
    wave = 1000.0 + 50 * np.sin(2 * np.pi * 5 * t)  # 5 Hz on a big offset
    buf.add(Trace(wave, header={"channel": "EHZ", "starttime": T0, "sampling_rate": 100.0}))
    buf.add(Trace(wave, header={"channel": "EHZ", "starttime": T0 + 20, "sampling_rate": 100.0}))
    _, raw = buf.snapshot("EHZ", 30)
    _, flt = buf.snapshot("EHZ", 30, bandpass=(1.0, 10.0))
    assert np.nanmean(raw) > 900 and abs(np.nanmean(flt)) < 5
    assert np.isnan(flt).sum() == 1
    assert 40 < np.nanmax(flt) < 60


def test_decimation_keeps_gap_marker():
    buf = RingBuffer()
    buf.add(trace("EHZ", T0, 3000))
    buf.add(trace("EHZ", T0 + 60, 3000))
    t, v = buf.snapshot("EHZ", 90, max_points=200)
    assert len(t) <= 201 and np.isnan(v).sum() == 1


def test_ring_buffer_lists_channels_with_data():
    buf = RingBuffer()
    assert buf.channels() == []
    buf.add(trace("EHZ", T0, 10))
    buf.add(trace("EHN", T0, 10))
    assert buf.channels() == ["EHN", "EHZ"]


def test_detector_gets_every_trace():
    seen = []

    class Spy:
        def feed(self, tr):
            seen.append(tr.stats.channel)

    stream = LiveStream(lambda: None, detector=Spy())
    stream._on_trace(trace("EHZ", T0, 10))
    stream._on_trace(trace("EHN", T0, 10))
    assert seen == ["EHZ", "EHN"]


def test_detector_failure_does_not_stop_the_stream():
    calls = []

    class Broken:
        def feed(self, tr):
            calls.append(1)
            raise RuntimeError("boom")

    stream = LiveStream(lambda: None, detector=Broken())
    stream._on_trace(trace("EHZ", T0, 100))
    stream._on_trace(trace("EHZ", T0 + 1, 100))
    assert len(calls) == 2                      # still called after the first failure
    assert stream.state == "live"
    t, v = stream.buffer.snapshot("EHZ", 10)
    assert len(t) == 200                        # data kept flowing into the ring buffer
