import numpy as np
from obspy import Stream, Trace, UTCDateTime

from rs3d.core.health import health

T0 = UTCDateTime("2026-10-12T00:00:00")


def tr(channel: str, start: float, seconds: float) -> Trace:
    return Trace(data=np.zeros(int(seconds * 100)),
                 header={"sampling_rate": 100.0, "starttime": T0 + start, "network": "AM", "station": "R77A7",
                         "location": "00", "channel": channel})


def test_full_coverage_has_no_gaps():
    h = health(Stream([tr("EHZ", 0, 100), tr("EHN", 0, 100)]), T0, T0 + 100)
    assert h.gaps == [] and h.completeness == 1.0


def test_gap_in_one_channel_counts_and_lists_once():
    st = Stream([tr("EHZ", 0, 40), tr("EHZ", 50, 50), tr("EHN", 0, 100)])
    h = health(st, T0, T0 + 100)
    assert [(a - T0, b - T0) for a, b in h.gaps] == [(40.0, 50.0)]
    assert abs(h.completeness - 0.9) < 1e-9


def test_edges_missing_count_as_gaps():
    h = health(Stream([tr("EHZ", 10, 80)]), T0, T0 + 100)
    assert [(a - T0, b - T0) for a, b in h.gaps] == [(0.0, 10.0), (90.0, 100.0)]
    assert abs(h.completeness - 0.8) < 1e-9


def test_empty_stream_is_one_big_gap():
    h = health(Stream(), T0, T0 + 100)
    assert h.completeness == 0.0 and len(h.gaps) == 1


def test_sample_rounding_is_not_a_gap():
    # two consecutive traces, 1 sample apart, are contiguous
    h = health(Stream([tr("EHZ", 0, 50), tr("EHZ", 50, 50)]), T0, T0 + 100)
    assert h.gaps == []
