"""ECharts option builders (plain dicts, no NiceGUI), so they can be unit-tested."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
from obspy import Stream, UTCDateTime

from rs3d.core.coverage import Segment, State

COLORS = {State.LOCAL: "#2e9e4f", State.REMOTE: "#9e9e9e", State.GAP: "#d23c3c"}
SELECTION = "rgba(47,111,222,0.25)"
EVENT_FILL = "rgba(211,47,47,0.18)"


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


def set_event_areas(options: dict, spans: list[tuple[float, float]]) -> None:
    """Shade each (start, end) in epoch seconds on every series of a time-axis waveform chart."""
    data = [[{"xAxis": a * 1000.0}, {"xAxis": b * 1000.0}] for a, b in spans]
    for s in options["series"]:
        s["markArea"] = {"silent": True, "itemStyle": {"color": EVENT_FILL}, "data": data}


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


def _bin(a: np.ndarray, n: int) -> np.ndarray:
    """Index of the output bin (0..n-1) for each input position, spreading len(a) evenly over n bins."""
    return np.minimum((np.arange(len(a)) * n) // max(len(a), 1), n - 1)


def spectrogram_options(times: np.ndarray, freqs: np.ndarray, power_db: np.ndarray, use_utc: bool = True,
                        max_cells: tuple[int, int] = (400, 200)) -> dict:
    """Heatmap of power_db (freqs x times). Cells are averaged down to max_cells; NaN (gap) cells are left out."""
    nx, ny = min(len(times), max_cells[0]), min(len(freqs), max_cells[1])
    bx, by = _bin(times, nx), _bin(freqs, ny)
    total = np.zeros((ny, nx))
    count = np.zeros((ny, nx))
    ok = ~np.isnan(power_db)
    np.add.at(total, (by[:, None].repeat(len(times), 1)[ok], bx[None, :].repeat(len(freqs), 0)[ok]), power_db[ok])
    np.add.at(count, (by[:, None].repeat(len(times), 1)[ok], bx[None, :].repeat(len(freqs), 0)[ok]), 1)
    mean = np.divide(total, count, out=np.full_like(total, np.nan), where=count > 0)
    tz = timezone.utc if use_utc else None
    x_first = [times[bx == i][0] for i in range(nx)]
    y_first = [freqs[by == i][0] for i in range(ny)]
    labels = [datetime.fromtimestamp(float(t), tz).strftime("%Y-%m-%d %H:%M:%S") for t in x_first]
    cells = [[int(i), int(j), round(float(mean[j, i]), 1)] for j in range(ny) for i in range(nx)
             if not np.isnan(mean[j, i])]
    values = [c[2] for c in cells] or [0.0, 1.0]
    lo, hi = float(np.percentile(values, 2)), float(np.percentile(values, 98))
    if hi <= lo:
        hi = lo + 1.0
    return {
        "animation": False,
        "grid": {"left": 70, "right": 90, "top": 8, "bottom": 40},
        "xAxis": {"type": "category", "data": labels, "axisLabel": {"hideOverlap": True}, "splitArea": {"show": False}},
        "yAxis": {"type": "category", "data": [f"{f:.1f}" for f in y_first], "name": "Hz", "nameLocation": "middle",
                  "nameGap": 48, "axisLabel": {"interval": max(ny // 6, 1) - 1}},
        "visualMap": {"min": lo, "max": hi, "calculable": True, "orient": "vertical", "right": 4, "top": "middle",
                      "text": ["dB", ""], "inRange": {"color": ["#313695", "#4575b4", "#abd9e9", "#fee090",
                                                                "#f46d43", "#a50026"]}},
        "tooltip": {"position": "top"},
        "series": [{"type": "heatmap", "data": cells, "progressive": 0}],
    }


def psd_options(freqs: np.ndarray, lo: np.ndarray, med: np.ndarray, hi: np.ndarray) -> dict:
    """Power spectral density summary: median with 10%/90% lines, log frequency axis."""
    def line(name: str, values: np.ndarray, **style) -> dict:
        data = [[float(f), None if np.isnan(v) else round(float(v), 2)] for f, v in zip(freqs, values)]
        return {"type": "line", "name": name, "showSymbol": False, "data": data, "lineStyle": style}
    return {
        "animation": False,
        "grid": {"left": 70, "right": 90, "top": 24, "bottom": 40},
        "legend": {"top": 0},
        "xAxis": {"type": "log", "name": "Hz", "nameLocation": "middle", "nameGap": 26},
        "yAxis": {"type": "value", "scale": True, "name": "dB", "nameLocation": "middle", "nameGap": 48},
        "tooltip": {"trigger": "axis"},
        "series": [line("10%", lo, width=1, type="dashed"), line("median", med, width=2),
                   line("90%", hi, width=1, type="dashed")],
    }


ROW_PX = 14
ROW_COLORS = ("#37474f", "#ec407a")
_GRID_TOP, _GRID_BOTTOM = 8, 36


def helicorder_height_px(n_rows: int) -> int:
    """Chart height in pixels so that one row is exactly ROW_PX tall."""
    return n_rows * ROW_PX + _GRID_TOP + _GRID_BOTTOM


def _hour_label(ts: float, utc: bool) -> str:
    dt = datetime.fromtimestamp(ts, timezone.utc if utc else None)
    return dt.strftime("%H:%M") if dt.minute == 0 else ""


def _label_js(labels: list[str]) -> str:
    return "(v) => " + json.dumps(labels) + "[Math.round(v)] ?? ''"


def helicorder_options(rows: list, scale: float, row_minutes: int = 30, click_every_s: float = 10.0) -> dict:
    """One line per row (y = row_index - value / scale), plus an invisible scatter grid that reports clicks.

    A click reports value [x_minutes, row_index] for series "click".
    """
    n = len(rows)
    series: list[dict] = []
    for i, row in enumerate(rows):
        data = [[round(float(s) / 60.0, 4), None if np.isnan(v) else round(float(i - v / scale), 3)]
                for s, v in zip(row.seconds, row.values)]
        series.append({"type": "line", "name": f"row{i}", "showSymbol": False, "silent": True,
                       "lineStyle": {"width": 1, "color": ROW_COLORS[i % 2]}, "data": data})
    per_row = int(row_minutes * 60 / click_every_s)
    grid = [[round((j + 0.5) * click_every_s / 60.0, 4), i] for i in range(n) for j in range(per_row)]
    series.append({"type": "scatter", "name": "click", "symbol": "rect", "symbolSize": [10, ROW_PX],
                   "itemStyle": {"opacity": 0.01}, "data": grid})
    utc_labels = [_hour_label(r.start.timestamp, True) for r in rows]
    local_labels = [_hour_label(r.start.timestamp, False) for r in rows]

    def y_axis(labels: list[str], position: str) -> dict:
        return {"type": "value", "inverse": True, "min": -0.5, "max": n - 0.5, "interval": 1, "position": position,
                "axisLine": {"show": False}, "axisTick": {"show": False}, "splitLine": {"show": False},
                "axisLabel": {":formatter": _label_js(labels)}}

    return {"animation": False, "tooltip": {"show": False},
            "grid": {"left": 56, "right": 56, "top": _GRID_TOP, "bottom": _GRID_BOTTOM},
            "xAxis": {"type": "value", "min": 0, "max": row_minutes, "name": "Minutes", "nameLocation": "middle",
                      "nameGap": 24, "interval": 5, "axisLine": {"onZero": False}},
            "yAxis": [y_axis(utc_labels, "left"), y_axis(local_labels, "right")],
            "series": series}


def helicorder_event_areas(rows: list, spans: list[tuple[float, float]], row_minutes: int = 30) -> list:
    """markArea pairs in the helicorder's own coordinates (x = minutes in the row, y = row index ± 0.5)."""
    out: list = []
    for i, row in enumerate(rows):
        r0 = row.start.timestamp
        r1 = r0 + row_minutes * 60
        for a, b in spans:
            if b < r0 or a >= r1:
                continue
            out.append([{"xAxis": round((max(a, r0) - r0) / 60.0, 4), "yAxis": i - 0.5},
                        {"xAxis": round((min(b, r1) - r0) / 60.0, 4), "yAxis": i + 0.5}])
    return out


def set_helicorder_events(options: dict, rows: list, spans: list[tuple[float, float]],
                          row_minutes: int = 30) -> None:
    """Mark events on a helicorder chart; the shading goes on the invisible "click" series (the last one)."""
    options["series"][-1]["markArea"] = {"silent": True, "itemStyle": {"color": EVENT_FILL},
                                         "data": helicorder_event_areas(rows, spans, row_minutes)}


def spectrum_options(freqs: np.ndarray, amplitude: np.ndarray) -> dict:
    """Log-log amplitude spectrum of one window."""
    data = [[float(f), float(a)] for f, a in zip(freqs, amplitude) if a > 0]
    return {"animation": False, "grid": {"left": 70, "right": 24, "top": 16, "bottom": 40},
            "xAxis": {"type": "log", "name": "Frequency in Hz", "nameLocation": "middle", "nameGap": 26},
            "yAxis": {"type": "log", "name": "Amplitude", "nameLocation": "middle", "nameGap": 52},
            "tooltip": {"trigger": "axis"},
            "series": [{"type": "line", "showSymbol": False, "data": data,
                        "lineStyle": {"width": 1, "color": "#e53935"}}]}


FREQ_COLORS = {"Z": "#0B4F6C", "N": "#F15A24", "E": "#475569"}


def frequency_options(channels: dict, units: str, log: bool = False) -> dict:
    """Median spectrum per channel (dB) with the peaks marked and labelled in Hz. `channels`: {name: ChannelResult}."""
    series = []
    for name, r in channels.items():
        color = FREQ_COLORS.get(name[-1:], "#888888")
        keep = r.freqs > 0
        data = [[round(float(f), 4), None if np.isnan(v) else round(float(v), 2)]
                for f, v in zip(r.freqs[keep], r.median_db[keep])]
        peaks = [{"coord": [round(p.freq, 4), round(p.level_db, 2)], "value": f"{p.freq:.2f}"} for p in r.peaks]
        series.append({"type": "line", "name": name, "showSymbol": False, "data": data,
                       "lineStyle": {"width": 1.5, "color": color}, "itemStyle": {"color": color},
                       "markPoint": {"symbol": "pin", "symbolSize": 42, "data": peaks,
                                     "label": {"formatter": "{c}", "fontSize": 10},
                                     "itemStyle": {"color": color}}})
    return {
        "animation": False,
        "grid": {"left": 70, "right": 24, "top": 30, "bottom": 46},
        "legend": {"top": 0},
        "xAxis": {"type": "log" if log else "value", "name": "Hz", "nameLocation": "middle", "nameGap": 28,
                  "min": 0.5 if log else 0, "max": 45 if log else 40},
        "yAxis": {"type": "value", "scale": True, "nameLocation": "middle", "nameGap": 52,
                  "name": "dB re 1 (m/s)²/Hz" if units == "m/s" else "dB re 1 count²/Hz"},
        "tooltip": {"trigger": "axis"},
        "series": series,
    }
