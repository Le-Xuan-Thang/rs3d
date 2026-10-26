import numpy as np
from obspy import Trace, UTCDateTime

from rs3d.core.models import Selection
from rs3d.core.preview import build_preview
from rs3d.core.store import Store

T0 = UTCDateTime("2026-10-12T00:00:00")


def write(root, channel, data):
    tr = Trace(data.astype("int32"), dict(network="AM", station="R77A7", location="00", channel=channel,
                                          sampling_rate=100.0, starttime=T0))
    path = Store(root).day_path("AM", "R77A7", "00", channel, T0.date)
    path.parent.mkdir(parents=True, exist_ok=True)
    tr.write(str(path), format="MSEED")


def test_preview_decimates_the_waveform_and_removes_the_offset(tmp_path):
    t = np.arange(3600 * 100) / 100.0
    write(tmp_path, "EHZ", 100000 + 800 * np.sin(2 * np.pi * 5 * t) + np.random.default_rng(0).normal(0, 20, len(t)))
    p = build_preview(Store(tmp_path), Selection("AM", "R77A7", "00", T0, T0 + 3600, channels=("EHZ",)))
    tt, vv = p.waveforms["EHZ"]
    assert len(tt) <= 2100 and abs(np.nanmedian(vv)) < 50
    assert vv.max() > 700 and vv.min() < -700  # min/max decimation keeps the peaks


def test_preview_loads_only_the_asked_channels(tmp_path):
    for ch in ("EHZ", "EHN"):
        write(tmp_path, ch, np.zeros(60000))
    p = build_preview(Store(tmp_path), Selection("AM", "R77A7", "00", T0, T0 + 600, channels=("EHN",)))
    assert list(p.waveforms) == ["EHN"]


def test_preview_of_an_empty_range_is_empty(tmp_path):
    p = build_preview(Store(tmp_path), Selection("AM", "R77A7", "00", T0, T0 + 600, channels=("EHZ",)))
    assert p.waveforms == {}
