import numpy as np
from obspy import UTCDateTime

from rs3d.app.charts import (COLORS, coverage_options, helicorder_event_areas, helicorder_options, set_event_areas,
                             set_helicorder_events, set_live_data, set_selection, set_stream_data, waveform_options)
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


def test_spectrogram_options_heatmap_skips_nan_and_caps_cells():
    from rs3d.app.charts import spectrogram_options
    times = 1.7e9 + np.arange(1000) * 10.0
    freqs = np.linspace(0, 50, 500)
    power = np.full((500, 1000), -100.0)
    power[:, 10] = np.nan
    opt = spectrogram_options(times, freqs, power, use_utc=True, max_cells=(100, 50))
    s = opt["series"][0]
    assert s["type"] == "heatmap"
    assert len(opt["xAxis"]["data"]) <= 100 and len(opt["yAxis"]["data"]) <= 50
    assert all(c[2] is not None and c[2] == c[2] for c in s["data"])  # no NaN cells
    assert opt["visualMap"]["min"] < opt["visualMap"]["max"]


def test_spectrogram_options_labels_follow_timezone():
    from rs3d.app.charts import spectrogram_options
    times = np.array([0.0, 10.0])
    freqs = np.array([0.0, 1.0])
    power = np.zeros((2, 2))
    utc = spectrogram_options(times, freqs, power, use_utc=True)["xAxis"]["data"][0]
    assert utc.startswith("1970-01-01 00:00")


def test_psd_options_log_axis_with_band():
    from rs3d.app.charts import psd_options
    f = np.array([0.1, 1.0, 10.0])
    opt = psd_options(f, np.array([-90.0, -80, -70]), np.array([-85.0, -75, -65]), np.array([-80.0, -70, -60]))
    assert opt["xAxis"]["type"] == "log"
    assert [s["name"] for s in opt["series"]] == ["10%", "median", "90%"]
    assert opt["series"][1]["data"][0] == [0.1, -85.0]


def _rows(n_with_data=48):
    from obspy import UTCDateTime
    from rs3d.core.helicorder import Row
    day = UTCDateTime("2026-10-12")
    rows = []
    for i in range(48):
        if i < n_with_data:
            rows.append(Row(day + i * 1800, np.array([0.0, 60.0, 61.0, 120.0]), np.array([1.0, np.nan, -2.0, 3.0])))
        else:
            rows.append(Row(day + i * 1800, np.array([]), np.array([])))
    return rows


def test_helicorder_options_rows_colours_and_offsets():
    from rs3d.app.charts import ROW_COLORS, helicorder_options
    opt = helicorder_options(_rows(), scale=2.0)
    lines = [s for s in opt["series"] if s["type"] == "line"]
    assert len(lines) == 48 and lines[0]["name"] == "row0"
    assert lines[0]["lineStyle"]["color"] == ROW_COLORS[0] and lines[1]["lineStyle"]["color"] == ROW_COLORS[1]
    # y = row_index - value / scale ; x in minutes ; NaN -> None
    assert lines[3]["data"][0] == [0.0, 3 - 1.0 / 2.0]
    assert lines[3]["data"][1][1] is None
    assert opt["yAxis"][0]["inverse"] is True and opt["xAxis"]["max"] == 30
    assert opt["xAxis"]["axisLine"]["onZero"] is False  # inverted y axis: keep the x axis at the bottom


def test_helicorder_click_grid_and_labels():
    from rs3d.app.charts import ROW_PX, helicorder_height_px, helicorder_options
    opt = helicorder_options(_rows(n_with_data=0), scale=1.0)
    click = next(s for s in opt["series"] if s["name"] == "click")
    assert click["type"] == "scatter" and len(click["data"]) == 48 * 180
    assert click["data"][0] == [round(5 / 60, 4), 0] and click["data"][-1][1] == 47
    assert helicorder_height_px(48) == 48 * ROW_PX + 44
    left = opt["yAxis"][0]["axisLabel"][":formatter"]
    assert '"00:00"' in left and '"01:00"' in left


def test_spectrum_options_is_log_log_and_drops_zeros():
    from rs3d.app.charts import spectrum_options
    opt = spectrum_options(np.array([1.0, 2.0, 3.0]), np.array([10.0, 0.0, 5.0]))
    assert opt["xAxis"]["type"] == "log" and opt["yAxis"]["type"] == "log"
    assert opt["series"][0]["data"] == [[1.0, 10.0], [3.0, 5.0]]


class _Row:
    def __init__(self, start):
        self.start = UTCDateTime(start)
        self.seconds = np.arange(0, 1800, 1.0)
        self.values = np.zeros(1800)


def test_set_event_areas_marks_every_series():
    opts = waveform_options(("EHZ", "EHN", "EHE"))
    set_event_areas(opts, [(100.0, 112.0)])
    for s in opts["series"]:
        area = s["markArea"]["data"]
        assert area == [[{"xAxis": 100000.0}, {"xAxis": 112000.0}]]
        assert s["markArea"]["silent"] is True


def test_set_event_areas_with_no_events_clears():
    opts = waveform_options(("EHZ",))
    set_event_areas(opts, [(1.0, 2.0)])
    set_event_areas(opts, [])
    assert opts["series"][0]["markArea"]["data"] == []


def test_helicorder_event_areas_inside_one_row():
    rows = [_Row("2026-10-12T00:00:00"), _Row("2026-10-12T00:30:00")]
    t0 = UTCDateTime("2026-10-12T00:35:00").timestamp
    areas = helicorder_event_areas(rows, [(t0, t0 + 60)])
    assert areas == [[{"xAxis": 5.0, "yAxis": 0.5}, {"xAxis": 6.0, "yAxis": 1.5}]]


def test_helicorder_event_areas_split_across_rows():
    rows = [_Row("2026-10-12T00:00:00"), _Row("2026-10-12T00:30:00")]
    t0 = UTCDateTime("2026-10-12T00:29:00").timestamp
    areas = helicorder_event_areas(rows, [(t0, t0 + 120)])
    assert areas == [[{"xAxis": 29.0, "yAxis": -0.5}, {"xAxis": 30.0, "yAxis": 0.5}],
                     [{"xAxis": 0.0, "yAxis": 0.5}, {"xAxis": 1.0, "yAxis": 1.5}]]


def test_helicorder_event_outside_day_is_ignored():
    rows = [_Row("2026-10-12T00:00:00")]
    t0 = UTCDateTime("2026-10-13T00:00:00").timestamp
    assert helicorder_event_areas(rows, [(t0, t0 + 10)]) == []


def test_set_helicorder_events_writes_to_click_series():
    rows = [_Row("2026-10-12T00:00:00")]
    opts = helicorder_options(rows, 1.0)
    t0 = rows[0].start.timestamp + 60
    set_helicorder_events(opts, rows, [(t0, t0 + 30)])
    assert opts["series"][-1]["name"] == "click"
    assert opts["series"][-1]["markArea"]["data"] == [[{"xAxis": 1.0, "yAxis": -0.5}, {"xAxis": 1.5, "yAxis": 0.5}]]
