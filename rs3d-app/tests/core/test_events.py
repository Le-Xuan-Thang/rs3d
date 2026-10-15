from pathlib import Path

import numpy as np
import pytest
from obspy import Stream, Trace, UTCDateTime, read

from rs3d.core.events import Event, EventDetector, EventSettings, detect, validate_settings

RATE = 100.0
T0 = 1_700_000_000.0


def make(seconds, burst=None, freq=3.0, amp=2000.0, seed=1, start=T0, channel="EHZ"):
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    x = rng.normal(0, 20, n)
    if burst:
        b0, b1 = burst
        t = np.arange(int(b0 * RATE), int(b1 * RATE)) / RATE
        x[int(b0 * RATE):int(b1 * RATE)] += amp * np.sin(2 * np.pi * freq * t)
    return Trace(x, header={"sampling_rate": RATE, "starttime": UTCDateTime(start), "channel": channel,
                            "network": "AM", "station": "R77A7"})


def test_noise_gives_no_event():
    assert detect(make(300), EventSettings()) == []


def test_burst_gives_one_event():
    ev = detect(make(300, burst=(120, 130)), EventSettings())
    assert len(ev) == 1
    e = ev[0]
    assert T0 + 119 < e.start < T0 + 125
    assert T0 + 130 < e.end < T0 + 160
    assert e.peak_ratio > 3.95 and e.source == "scan" and e.channel == "EHZ"
    assert e.peak_amplitude > 100


def test_burst_in_warmup_ignored():
    assert detect(make(300, burst=(5, 10)), EventSettings()) == []


def test_other_channel_ignored():
    assert detect(make(300, burst=(120, 130), channel="EHN"), EventSettings()) == []


def test_out_of_band_burst_removed():
    assert detect(make(300, burst=(120, 130), freq=30.0), EventSettings()) == []


def test_gap_restarts_warmup():
    a = make(200, start=T0)
    b = make(200, burst=(10, 20), start=T0 + 400)  # burst 10 s after the gap: inside the new warm-up
    assert detect(Stream([a, b]), EventSettings()) == []


def test_gap_closes_open_event():
    got = []
    d = EventDetector(EventSettings(), got.append)
    d.feed(make(200, burst=(150, 199.99), amp=5000))
    assert d.active
    d.feed(make(100, start=T0 + 1000))
    assert not d.active and len(got) == 1
    assert got[0].end <= T0 + 200


def test_chunked_equals_whole():
    tr = make(300, burst=(120, 130))
    whole = detect(tr, EventSettings())
    got = []
    d = EventDetector(EventSettings(), got.append, source="scan")
    for i in range(0, tr.stats.npts, 137):
        piece = tr.copy()
        piece.data = tr.data[i:i + 137].copy()
        piece.stats.starttime = tr.stats.starttime + i / RATE
        d.feed(piece)
    d.flush()
    assert len(got) == len(whole) == 1
    assert abs(got[0].start - whole[0].start) < 1e-6 and abs(got[0].end - whole[0].end) < 1e-6


def test_on_start_fires_before_end():
    order = []
    d = EventDetector(EventSettings(), lambda e: order.append("end"), lambda t, r: order.append("start"))
    d.feed(make(300, burst=(120, 130)))
    d.flush()
    assert order == ["start", "end"]


def test_disabled_detector_silent():
    assert detect(make(300, burst=(120, 130)), EventSettings(enabled=False)) == []


def test_flat_data_gives_no_event():  # Review Focus 1
    for value in (0.0, 5000.0):
        tr = Trace(np.full(int(200 * RATE), value), header={"sampling_rate": RATE, "starttime": UTCDateTime(T0),
                                                            "channel": "EHZ"})
        with np.errstate(all="raise"):
            assert detect(tr, EventSettings()) == []


def test_resent_packet_is_safe():  # Review Focus 2
    tr = make(300)
    got = []
    d = EventDetector(EventSettings(), got.append)
    d.feed(tr)
    again = tr.copy()
    again.trim(tr.stats.starttime + 100, tr.stats.starttime + 110)  # a chunk we already delivered
    d.feed(again)
    d.flush()
    assert got == []


def test_detect_closes_event_at_end_of_data():  # Review Focus 3
    ev = detect(make(200, burst=(150, 199.99), amp=5000), EventSettings())
    assert len(ev) == 1 and ev[0].end <= T0 + 200


def test_validate():
    assert validate_settings(EventSettings()) == ""
    assert "LTA" in validate_settings(EventSettings(lta=5))
    assert "Reset" in validate_settings(EventSettings(reset=5))
    assert "Band-pass" in validate_settings(EventSettings(lowpass=60))
    assert "Band-pass" in validate_settings(EventSettings(highpass=0))
    assert "Channel" in validate_settings(EventSettings(channel="XXX"))


REAL = Path(__file__).resolve().parents[3] / "rsudp_out" / "data" / "fdsnws.mseed"


@pytest.mark.skipif(not REAL.exists(), reason="local rsudp_out/data/fdsnws.mseed is not in the repository")
def test_real_file_gives_a_plausible_number_of_events():
    st = read(str(REAL)).select(channel="EHZ")
    events = detect(st, EventSettings())
    assert 1 <= len(events) < 200
    assert all(e.end > e.start and e.peak_ratio > 3.95 for e in events)
