import numpy as np
from obspy import UTCDateTime

from rs3d.app.charts import COLORS, coverage_options, set_live_data, set_selection, set_stream_data, waveform_options
from rs3d.core.coverage import Segment, State

def test_waveform_options_one_panel_per_channel():
    opt = waveform_options(("EHZ", "EHN", "EHE"))
    assert [s["name"] for s in opt["series"]] == ["EHZ", "EHN", "EHE"]
    assert len(opt["grid"]) == len(opt["xAxis"]) == len(opt["yAxis"]) == 3
    assert opt["useUTC"] is True
    assert waveform_options(("EHZ",), use_utc=False)["useUTC"] is False


def test_live_data_breaks_line_at_gap():
    opt = waveform_options(("EHZ",))
    t = np.array([1.0, 1.01, 1.02, 1.03])
    v = np.array([1.0, np.nan, 2.0, 3.0])
    set_live_data(opt, {"EHZ": (t, v)}, (0.0, 2.0))
    assert opt["series"][0]["data"][1] == [1010.0, None]
    assert opt["xAxis"][0]["min"] == 0.0 and opt["xAxis"][0]["max"] == 2000.0


def test_stream_data_from_fixture(store):
    from rs3d.core.models import Selection
    from tests.conftest import GAP_END, GAP_START
    st = store.load(Selection("AM", "R77A7", "00", GAP_START - 60, GAP_END + 60))
    opt = waveform_options(("EHZ", "EHN", "EHE"))
    set_stream_data(opt, st)
    ehz = opt["series"][0]["data"]
    assert any(p[1] is None for p in ehz) and len(ehz) <= 4000


def test_coverage_colours_slider_and_future_blank():
    view = (UTCDateTime("2026-10-12"), UTCDateTime("2026-10-13"))
    segs = [Segment(view[0], UTCDateTime("2026-10-12T06:00"), State.LOCAL),
            Segment(UTCDateTime("2026-10-12T06:00"), view[1], State.REMOTE)]
    opt = coverage_options(view, segs, (UTCDateTime("2026-10-12T10:00"), UTCDateTime("2026-10-12T11:00")),
                           now=UTCDateTime("2026-10-12T17:00"))
    areas = opt["series"][0]["markArea"]["data"]
    assert [a[0]["itemStyle"]["color"] for a in areas] == [COLORS[State.LOCAL], COLORS[State.REMOTE]]
    assert areas[1][1]["xAxis"] == UTCDateTime("2026-10-12T17:00").timestamp * 1000
    dz = opt["dataZoom"][0]
    assert dz["xAxisIndex"] == 1  # slider drives the hidden axis, not the coverage strip
    set_selection(opt, (UTCDateTime("2026-10-12T12:00"), UTCDateTime("2026-10-12T13:00")))
    assert dz["startValue"] == UTCDateTime("2026-10-12T12:00").timestamp * 1000
