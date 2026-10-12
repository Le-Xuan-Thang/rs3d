"""ECharts option builders (plain dicts, no NiceGUI), so they can be unit-tested."""

from __future__ import annotations

import numpy as np
from obspy import Stream, UTCDateTime

from rs3d.core.coverage import Segment, State

COLORS = {State.LOCAL: "#2e9e4f", State.REMOTE: "#9e9e9e", State.GAP: "#d23c3c"}
SELECTION = "rgba(47,111,222,0.25)"


def _ms(t: UTCDateTime | float) -> float:
    return (t.timestamp if isinstance(t, UTCDateTime) else t) * 1000.0


def _points(times: np.ndarray, values: np.ndarray) -> list[list]:
    """[[ms, value], ...] with NaN -> None so ECharts breaks the line at gaps."""
    return [[float(t) * 1000.0, None if np.isnan(v) else float(v)] for t, v in zip(times, values)]


def waveform_options(channels: tuple[str, ...], use_utc: bool = True) -> dict:
    """One stacked panel per channel, shared time axis. use_utc=False labels the axis in browser time."""
    n = len(channels)
    height = 100 / n
    grids, xaxes, yaxes, series = [], [], [], []
    for i, ch in enumerate(channels):
        grids.append({"left": 70, "right": 16, "top": f"{i * height + 2}%", "height": f"{height - 8}%"})
        xaxes.append({"type": "time", "gridIndex": i, "axisLabel": {"show": i == n - 1}})
        yaxes.append({"type": "value", "gridIndex": i, "scale": True, "name": ch,
                      "nameLocation": "middle", "nameGap": 52, "splitNumber": 2,
                      "axisLabel": {"formatter": "{value}"}})
        series.append({"type": "line", "name": ch, "xAxisIndex": i, "yAxisIndex": i, "showSymbol": False,
                       "sampling": "lttb", "lineStyle": {"width": 1}, "connectNulls": False, "data": []})
    return {"animation": False, "useUTC": use_utc, "grid": grids, "xAxis": xaxes, "yAxis": yaxes, "series": series,
            "tooltip": {"trigger": "axis"}, "axisPointer": {"link": [{"xAxisIndex": "all"}]}}


def set_live_data(options: dict, snapshots: dict[str, tuple[np.ndarray, np.ndarray]],
                  window: tuple[float, float]) -> None:
    for i, s in enumerate(options["series"]):
        t, v = snapshots.get(s["name"], (np.array([]), np.array([])))
        s["data"] = _points(t, v)
        options["xAxis"][i]["min"] = window[0] * 1000.0
        options["xAxis"][i]["max"] = window[1] * 1000.0


def set_stream_data(options: dict, st: Stream, max_points: int = 4000) -> None:
    """Fill a waveform chart from an ObsPy Stream (gaps -> None)."""
    for s in options["series"]:
        pts: list[list] = []
        for tr in sorted(st.select(channel=s["name"]), key=lambda x: x.stats.starttime):
            step = max(1, tr.stats.npts * len(st) // max_points)
            t = tr.stats.starttime.timestamp + np.arange(0, tr.stats.npts, step) / tr.stats.sampling_rate
            if pts:
                pts.append([pts[-1][0] + 1, None])
            pts += _points(t, tr.data[::step].astype(float))
        s["data"] = pts
    for x in options["xAxis"]:
        x.pop("min", None)
        x.pop("max", None)


def coverage_options(view: tuple[UTCDateTime, UTCDateTime], segments: list[Segment],
                     selection: tuple[UTCDateTime, UTCDateTime], now: UTCDateTime | None = None,
                     use_utc: bool = True) -> dict:
    """Coloured coverage strip; the slider below it is the Start/End selection.

    The slider drives a hidden second x-axis with the same extent, so moving it never
    zooms the coverage strip itself. Time after `now` is left blank.
    """
    areas = []
    for s in segments:
        end = min(s.end, now) if now is not None else s.end
        if end > s.start:
            areas.append([{"xAxis": _ms(s.start), "itemStyle": {"color": COLORS[s.state]}}, {"xAxis": _ms(end)}])
    extent = [[_ms(view[0]), 0], [_ms(view[1]), 0]]
    return {
        "animation": False,
        "useUTC": use_utc,
        "grid": [{"left": 8, "right": 8, "top": 4, "height": 28},
                 {"left": 8, "right": 8, "top": 60, "height": 1, "show": False}],
        "xAxis": [{"type": "time", "gridIndex": 0, "min": _ms(view[0]), "max": _ms(view[1]),
                   "axisLabel": {"hideOverlap": True}},
                  {"type": "time", "gridIndex": 1, "min": _ms(view[0]), "max": _ms(view[1]), "show": False}],
        "yAxis": [{"type": "value", "gridIndex": 0, "show": False, "min": 0, "max": 1},
                  {"type": "value", "gridIndex": 1, "show": False, "min": 0, "max": 1}],
        "series": [{"type": "line", "xAxisIndex": 0, "yAxisIndex": 0, "data": extent, "showSymbol": False,
                    "lineStyle": {"opacity": 0}, "silent": True, "markArea": {"silent": True, "data": areas}},
                   {"type": "line", "xAxisIndex": 1, "yAxisIndex": 1, "data": extent, "showSymbol": False,
                    "lineStyle": {"opacity": 0}, "silent": True}],
        "dataZoom": [{"type": "slider", "xAxisIndex": 1, "filterMode": "none", "top": 52, "height": 22,
                      "startValue": _ms(selection[0]), "endValue": _ms(selection[1]),
                      "showDetail": False, "brushSelect": True, "fillerColor": SELECTION,
                      "dataBackground": {"lineStyle": {"opacity": 0}, "areaStyle": {"opacity": 0}}}],
    }


def set_selection(options: dict, selection: tuple[UTCDateTime, UTCDateTime]) -> None:
    dz = options["dataZoom"][0]
    dz.pop("start", None)
    dz.pop("end", None)
    dz["startValue"], dz["endValue"] = _ms(selection[0]), _ms(selection[1])
