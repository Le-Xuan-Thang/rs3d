# Helicorder and Detail View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 24-hour helicorder page to `rs3d-app` where a click on a row opens a zoomable detail view (waveform, spectra, spectrogram) with a Waveform Clipboard that saves a PNG.

**Architecture:** A pure `core/helicorder.py` loads one channel of one UTC day, splits it into 48 rows of 30 minutes and reduces each row to min/max pairs. `app/charts.py` gets two new plain-dict ECharts builders. A new `/helicorder` page draws the rows and turns a click (reported by an invisible grid of scatter points) into a time. A `DetailPanel` class (`app/detail.py`) shows the clicked window in three switchable modes and opens the clipboard dialog.

**Tech Stack:** Python 3.11+, NiceGUI 3 (`ui.echart`), ObsPy, NumPy, SciPy, matplotlib, pytest, Playwright (Chrome) for the browser test.

**Spec:** `docs/superpowers/specs/2026-10-15-helicorder-detail-design.md`

## Global Constraints

- All paths below are relative to the repository root `/home/thang/NCREP-RaspberryShake`; the app lives in `rs3d-app/`. Run `uv run pytest` from `rs3d-app/`.
- Rows are 30 minutes, 48 per UTC day, aligned to UTC midnight. The left axis shows UTC hours, the right axis local hours.
- No DataView code, logo or watermark; every user-facing string goes in `rs3d-app/src/rs3d/help/en.toml` under `[labels...]` and is read with `label("...")`.
- Only the local archive is used (no network, no Shake). `m/s` needs an instrument response, as on the Data page.
- Charts are plain dicts built in `app/charts.py` (no NiceGUI imports there) so they are unit-testable.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Default `pytest` skips `e2e` and `device` markers; run the browser test with `uv run pytest -m e2e`.
- TDD for every task: write the test, watch it fail for the right reason, then implement.

## Review Focus

Inputs and conditions the spec implies but does not spell out, most likely first:

1. **Click on a row with no data** (day only partly recorded, or inside a gap): the detail view says "No data in this window" and does not crash. Pinned in Task 6.
2. **A full 24 h of 100 Hz data**: building the 48 rows must stay fast (under 2 s) and produce about 3,000 points per row. Pinned in Task 2.
3. **`m/s` selected but no instrument response available** (offline): clear error, page falls back to counts instead of an empty chart. Pinned in Tasks 2 and 5.
4. **Very short fragments with the band-pass on** (a few samples left between gaps): filtering must not raise. Pinned in Task 2.
5. **Zooming far in or out**: the window is clamped to between 5 seconds and 1 hour so it can never become empty or the whole day. Pinned in Task 2.

---

### Task 1: Spike — confirm click reporting and axis labels, then update the spec

**Files:**
- Create (scratch, not committed): `<scratchpad>/spike_click.py`, `<scratchpad>/spike_drive.py`
- Modify: `docs/superpowers/specs/2026-10-15-helicorder-detail-design.md` ("Click handling and spike" and "`core/helicorder.py`" sections)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: a recorded decision. Either (A) "a grid of invisible scatter points reports `[x_minutes, row_index]` through `on_point_click`, and `":formatter"` axis labels work" — which the rest of this plan assumes — or (B) a changed mechanism that you write into the spec and this plan's Tasks 4 and 5 before continuing.

This task changes no product code.

- [ ] **Step 1: Write the spike app** (`<scratchpad>` is the session scratchpad directory)

```python
# spike_click.py — throwaway: does an invisible scatter grid report clicks, and do ":formatter" labels render?
import json

from nicegui import ui

ROWS, PER_ROW, ROW_PX = 6, 18, 14
labels = ["00:00", "", "01:00", "", "02:00", ""]
points = [[round((j + 0.5) * 30 / PER_ROW, 3), i] for i in range(ROWS) for j in range(PER_ROW)]
options = {
    "animation": False,
    "tooltip": {"show": False},
    "grid": {"left": 60, "right": 60, "top": 8, "bottom": 36},
    "xAxis": {"type": "value", "min": 0, "max": 30, "name": "Minutes"},
    "yAxis": [{"type": "value", "inverse": True, "min": -0.5, "max": ROWS - 0.5, "interval": 1,
               "axisLabel": {":formatter": "(v) => " + json.dumps(labels) + "[Math.round(v)] ?? ''"}}],
    "series": [{"type": "scatter", "name": "click", "symbol": "rect", "symbolSize": [10, ROW_PX],
                "itemStyle": {"opacity": 0.01}, "data": points}],
}
chart = ui.echart(options).classes("w-full").style(f"height: {ROWS * ROW_PX + 44}px")
out = ui.label("none").props("id=out")
chart.on_point_click(lambda e: out.set_text(f"{e.series_name} {e.value}"))
ui.run(port=8841, show=False, reload=False)
```

- [ ] **Step 2: Write the driver and run both**

```python
# spike_drive.py
import sys
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    page = b.new_page(viewport={"width": 1000, "height": 400})
    page.goto("http://127.0.0.1:8841")
    page.wait_for_selector("canvas")
    box = page.locator("canvas").first.bounding_box()
    # plot area: left 60, right 60, top 8, bottom 36; row 2 (0-based), x = 10 minutes
    plot_w = box["width"] - 120
    x = box["x"] + 60 + plot_w * (10 / 30)
    y = box["y"] + 8 + 14 * (2 + 0.5)
    page.mouse.click(x, y)
    page.wait_for_timeout(500)
    print("LABEL:", page.locator("#out").inner_text())
    page.screenshot(path=sys.argv[1])
    b.close()
```

Run: `cd rs3d-app && (uv run python <scratchpad>/spike_click.py &) ; sleep 5 ; uv run python <scratchpad>/spike_drive.py <scratchpad>/spike.png`
Expected: `LABEL: click [10.0..., 2]` (x within one point spacing of 10, y exactly 2). Open the PNG: the left axis should show `00:00`, `01:00`, `02:00` at rows 0, 2, 4 and nothing at the odd rows.

- [ ] **Step 3: Decide and record**

If the label shows a `click` series with `[x, 2]` and the axis labels render: mechanism (A) is confirmed. Edit the spec: in "`app/charts.py`" and "Click handling and spike", replace "transparent full-width band" with "an invisible grid of scatter points (one every 10 seconds per row, `symbolSize [10, 14]`, chart height `48*14+44` px) whose `on_point_click` value is `[x_minutes, row_index]`"; delete the "(plus the next day's first minutes when a row crosses midnight)" clause in the `rows(...)` bullet (rows are midnight-aligned and never cross midnight); delete the fallback sentence. If it fails, stop, write the observed result into the spec, and revise Tasks 4 and 5 with the user before continuing.

- [ ] **Step 4: Commit the spec change**

```bash
git add docs/superpowers/specs/2026-10-15-helicorder-detail-design.md
git commit -m "docs: record helicorder click mechanism after spike

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `core/helicorder.py` — rows, scale, click time, window math

**Files:**
- Create: `rs3d-app/src/rs3d/core/helicorder.py`
- Create: `rs3d-app/tests/core/test_helicorder.py`
- Modify: `rs3d-app/src/rs3d/core/live.py` (rename `_minmax_decimate` to `minmax_decimate`), `rs3d-app/tests/core/test_live.py` (same rename if it imports it)

**Interfaces:**
- Consumes: `rs3d.core.store.Store.load(Selection) -> Stream`; `rs3d.core.export.process(st, sel, inventory) -> Stream`; `rs3d.core.models.Selection`; `rs3d.core.live.minmax_decimate(t, v, max_points) -> (t, v)` (renamed here, NaN entries in `v` separate segments).
- Produces:
  - `ROW_MINUTES = 30`, `POINTS_PER_ROW = 3000`, `MIN_SPAN = 5.0`, `MAX_SPAN = 3600.0`
  - `@dataclass(frozen=True) Row(start: UTCDateTime, seconds: np.ndarray, values: np.ndarray)` — `seconds` are offsets from `start`, NaN in `values` marks a gap.
  - `process_safe(st: Stream, sel: Selection, inventory: Inventory | None) -> Stream`
  - `load_day(store, net, sta, loc, channel, day: date, units="counts", band=None, inventory=None) -> Stream`
  - `load_window(store, net, sta, loc, channel, start: UTCDateTime, end: UTCDateTime, units="counts", band=None, inventory=None) -> Stream`
  - `build_rows(st: Stream, day_start: UTCDateTime, row_minutes: int = 30, points: int = 3000) -> list[Row]`
  - `scale_for(rows: list[Row], factor: float = 1.0) -> float` — amplitude that maps to one row height; larger `factor` = bigger traces.
  - `click_to_time(day_start: UTCDateTime, row_minutes: int, row_index: int, x_fraction: float) -> UTCDateTime`
  - `zoom_window(start, end, factor) -> (UTCDateTime, UTCDateTime)` (factor 2 = zoom out), `shift_window(start, end, direction) -> (UTCDateTime, UTCDateTime)` (±½ span)

- [ ] **Step 1: Rename the shared decimator**

Run: `cd rs3d-app && grep -rn "_minmax_decimate" src tests`
Then: `sed -i 's/_minmax_decimate/minmax_decimate/g' $(grep -rl "_minmax_decimate" src tests)`
Run: `uv run pytest -q` — Expected: all pass (pure rename).

- [ ] **Step 2: Write the failing tests**

```python
# tests/core/test_helicorder.py
import time
from datetime import date

import numpy as np
from obspy import Stream, Trace, UTCDateTime

from rs3d.core.helicorder import (MAX_SPAN, MIN_SPAN, build_rows, click_to_time, load_day, load_window,
                                  process_safe, scale_for, shift_window, zoom_window)
from rs3d.core.models import Selection
from tests.conftest import DAY2

DAY = UTCDateTime("2026-10-12T00:00:00")


def trace(start_s: float, data: np.ndarray, rate: float = 100.0) -> Trace:
    return Trace(data=data.astype("float64"), header={
        "network": "AM", "station": "R77A7", "location": "00", "channel": "EHZ",
        "sampling_rate": rate, "starttime": DAY + start_s})


def test_48_rows_with_start_times():
    rows = build_rows(Stream([trace(0, np.zeros(100))]), DAY)
    assert len(rows) == 48
    assert rows[1].start - rows[0].start == 1800 and rows[47].start == DAY + 47 * 1800


def test_peak_survives_decimation():
    data = np.zeros(180000)  # 30 minutes
    data[90050] = 5000.0     # t = 900.5 s
    rows = build_rows(Stream([trace(0, data)]), DAY, points=300)
    r = rows[0]
    assert len(r.values) <= 320 and r.values.max() == 5000.0
    assert abs(r.seconds[np.argmax(r.values)] - 900.5) < 0.011


def test_gap_between_traces_is_one_nan_inside_the_gap():
    st = Stream([trace(0, np.ones(6000)), trace(120, np.ones(6000))])  # 0-60 s and 120-180 s
    r = build_rows(st, DAY)[0]
    nan = np.flatnonzero(np.isnan(r.values))
    assert len(nan) == 1 and 60 < r.seconds[nan[0]] < 120


def test_contiguous_traces_have_no_nan():
    st = Stream([trace(0, np.ones(6000)), trace(60, np.ones(6000))])
    assert not np.isnan(build_rows(st, DAY)[0].values).any()


def test_rows_without_data_are_empty():
    rows = build_rows(Stream([trace(0, np.ones(100))]), DAY)
    assert len(rows[0].values) > 0 and all(len(r.values) == 0 for r in rows[1:])


def test_fixture_store_day_has_gap_in_first_row_only(store):
    st = load_day(store, "AM", "R77A7", "00", "EHZ", DAY2)
    rows = build_rows(st, DAY)
    assert np.isnan(rows[0].values).sum() == 1          # 00:02-00:03 hole
    assert all(len(r.values) == 0 for r in rows[1:])    # data ends 00:10


def test_full_day_of_100hz_is_fast_and_bounded():
    big = trace(0, np.random.default_rng(0).normal(0, 100, 86400 * 100))
    t0 = time.perf_counter()
    rows = build_rows(Stream([big]), DAY)
    assert time.perf_counter() - t0 < 2.0
    assert all(len(r.values) <= 3100 for r in rows)


def test_scale_ignores_one_huge_outlier():
    quiet = np.ones(6000)
    spike = np.ones(6000)
    spike[3000] = 1e6
    rows = build_rows(Stream([trace(0, quiet), trace(1800, spike)]), DAY)
    assert scale_for(rows) < 10
    assert scale_for(rows, factor=2.0) == scale_for(rows) / 2
    assert scale_for(build_rows(Stream(), DAY)) == 1.0


def test_click_to_time_maps_row_and_fraction():
    assert click_to_time(DAY, 30, 0, 0.0) == DAY
    assert click_to_time(DAY, 30, 2, 0.5) == DAY + 2 * 1800 + 900
    assert click_to_time(DAY, 30, 1, 1.7) == DAY + 2 * 1800  # clamped to the row end


def test_zoom_and_shift_windows_and_clamp():
    a, b = DAY + 100, DAY + 220  # 120 s
    za, zb = zoom_window(a, b, 2.0)
    assert zb - za == 240.0
    assert abs((za.timestamp + zb.timestamp) / 2 - (a.timestamp + b.timestamp) / 2) < 1e-6
    sa, sb = shift_window(a, b, 1)
    assert sa - a == 60 and sb - b == 60
    ta, tb = zoom_window(a, b, 0.001)
    assert tb - ta == MIN_SPAN
    ua, ub = zoom_window(a, b, 1000.0)
    assert ub - ua == MAX_SPAN


def test_window_with_band_pass_survives_tiny_fragments(store):
    sel = Selection("AM", "R77A7", "00", DAY + 0, DAY + 600, channels=("EHZ",), filter=(1.0, 10.0))
    st = Stream([trace(0, np.ones(10))])  # 10 samples: too short for a zero-phase filter
    assert len(process_safe(st, sel, None)) == 0  # dropped, no exception
    ok = load_window(store, "AM", "R77A7", "00", "EHZ", DAY + 10, DAY + 100, band=(1.0, 10.0))
    assert len(ok) >= 1


def test_metres_per_second_without_response_raises_clearly(store):
    import pytest
    with pytest.raises(ValueError, match="response"):
        load_window(store, "AM", "R77A7", "00", "EHZ", DAY + 10, DAY + 100, units="m/s")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_helicorder.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'rs3d.core.helicorder'`.

- [ ] **Step 4: Write the implementation**

```python
# src/rs3d/core/helicorder.py
"""Helicorder data: one channel of one UTC day as rows of 30 minutes, reduced to min/max pairs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
from obspy import Inventory, Stream, UTCDateTime

from rs3d.core.export import process
from rs3d.core.live import minmax_decimate
from rs3d.core.models import Selection
from rs3d.core.store import Store

ROW_MINUTES = 30
POINTS_PER_ROW = 3000
MIN_SPAN = 5.0      # seconds: smallest detail window
MAX_SPAN = 3600.0   # seconds: largest detail window


@dataclass(frozen=True)
class Row:
    start: UTCDateTime
    seconds: np.ndarray  # offsets from `start`
    values: np.ndarray   # NaN marks a gap


def process_safe(st: Stream, sel: Selection, inventory: Inventory | None) -> Stream:
    """Like export.process, but a fragment too short to filter is dropped instead of raising."""
    if sel.units == "m/s" and inventory is None:
        raise ValueError("units 'm/s' need an instrument response (inventory)")
    out = Stream()
    for tr in st:
        try:
            out += process(Stream([tr]), sel, inventory)
        except ValueError:
            continue
    return out


def load_window(store: Store, net: str, sta: str, loc: str, channel: str, start: UTCDateTime, end: UTCDateTime,
                units: str = "counts", band: tuple[float, float] | None = None,
                inventory: Inventory | None = None) -> Stream:
    sel = Selection(net, sta, loc, start, end, channels=(channel,), filter=band, units=units)
    return process_safe(store.load(sel), sel, inventory)


def load_day(store: Store, net: str, sta: str, loc: str, channel: str, day: date, units: str = "counts",
             band: tuple[float, float] | None = None, inventory: Inventory | None = None) -> Stream:
    start = UTCDateTime(day.year, day.month, day.day)
    return load_window(store, net, sta, loc, channel, start, start + 86400, units, band, inventory)


def build_rows(st: Stream, day_start: UTCDateTime, row_minutes: int = ROW_MINUTES,
               points: int = POINTS_PER_ROW) -> list[Row]:
    span = row_minutes * 60
    rows: list[Row] = []
    for i in range(24 * 60 // row_minutes):
        a = day_start + i * span
        t_parts: list[np.ndarray] = []
        v_parts: list[np.ndarray] = []
        for tr in sorted(st.slice(a, a + span - 1e-6), key=lambda x: x.stats.starttime):
            delta = tr.stats.delta
            t = (tr.stats.starttime - a) + np.arange(tr.stats.npts) * delta
            if t_parts and t[0] - t_parts[-1][-1] > 1.5 * delta:
                t_parts.append(np.array([t[0] - 0.5 * delta]))
                v_parts.append(np.array([np.nan]))
            t_parts.append(t)
            v_parts.append(tr.data.astype(float))
        if not t_parts:
            rows.append(Row(a, np.array([]), np.array([])))
            continue
        t, v = np.concatenate(t_parts), np.concatenate(v_parts)
        if len(t) > points:
            t, v = minmax_decimate(t, v, points)
        rows.append(Row(a, t, v))
    return rows


def scale_for(rows: list[Row], factor: float = 1.0) -> float:
    """Amplitude that maps to one row height, shared by all rows. A single huge event does not flatten the day."""
    parts = [np.abs(r.values[np.isfinite(r.values)]) for r in rows if len(r.values)]
    values = np.concatenate(parts) if parts else np.array([])
    if values.size == 0:
        return 1.0
    base = 2.0 * float(np.percentile(values, 99))
    return (base or 1.0) / factor


def click_to_time(day_start: UTCDateTime, row_minutes: int, row_index: int, x_fraction: float) -> UTCDateTime:
    span = row_minutes * 60
    return day_start + row_index * span + min(max(x_fraction, 0.0), 1.0) * span


def zoom_window(start: UTCDateTime, end: UTCDateTime, factor: float) -> tuple[UTCDateTime, UTCDateTime]:
    """Same centre, span multiplied by `factor` (2 = zoom out), clamped to [MIN_SPAN, MAX_SPAN]."""
    centre = (start.timestamp + end.timestamp) / 2
    span = min(max((end - start) * factor, MIN_SPAN), MAX_SPAN)
    return UTCDateTime(centre - span / 2), UTCDateTime(centre + span / 2)


def shift_window(start: UTCDateTime, end: UTCDateTime, direction: int) -> tuple[UTCDateTime, UTCDateTime]:
    step = (end - start) / 2 * direction
    return start + step, end + step
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/core/test_helicorder.py -v`
Expected: all pass. If the tiny-fragment test does not drop the 10-sample trace (the filter did not raise), lower the sample count in the test until `sosfiltfilt` raises, then keep it.

- [ ] **Step 6: Run the whole suite and commit**

Run: `uv run pytest -q` — Expected: all pass.

```bash
git add rs3d-app/src/rs3d/core/helicorder.py rs3d-app/src/rs3d/core/live.py rs3d-app/tests/core
git commit -m "feat(rs3d-app): helicorder data core (rows, scale, click time, window math)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `amplitude_spectrum` in `core/spectro.py`

**Files:**
- Modify: `rs3d-app/src/rs3d/core/spectro.py`
- Test: `rs3d-app/tests/core/test_spectro.py`

**Interfaces:**
- Consumes: `obspy.Trace`.
- Produces: `amplitude_spectrum(tr: Trace) -> tuple[np.ndarray, np.ndarray]` — `(freqs, amplitude)`, DC bin dropped, Hann window, amplitude scaled so a sine of amplitude `A` reads about `A`. Returns two empty arrays for fewer than 8 samples.

- [ ] **Step 1: Write the failing test** (append to `tests/core/test_spectro.py`)

```python
def test_amplitude_spectrum_peak_and_scale():
    from rs3d.core.spectro import amplitude_spectrum
    t = np.arange(0, 120, 0.01)
    freqs, amp = amplitude_spectrum(_trace(1000 * np.sin(2 * np.pi * 5 * t)))
    i = np.argmax(amp)
    assert abs(freqs[i] - 5.0) < 0.05
    assert abs(amp[i] - 1000) / 1000 < 0.05
    assert freqs[0] > 0


def test_amplitude_spectrum_of_tiny_trace_is_empty():
    from rs3d.core.spectro import amplitude_spectrum
    f, a = amplitude_spectrum(_trace(np.ones(5)))
    assert len(f) == 0 and len(a) == 0
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/core/test_spectro.py -k amplitude -v` — Expected: FAIL `ImportError: cannot import name 'amplitude_spectrum'`.

- [ ] **Step 3: Implement** (append to `src/rs3d/core/spectro.py`)

```python
def amplitude_spectrum(tr: Trace) -> tuple[np.ndarray, np.ndarray]:
    """(freqs, amplitude) of one window. Hann-tapered, DC bin dropped; a sine of amplitude A reads about A."""
    data = np.ma.getdata(tr.data).astype(float)
    if len(data) < 8:
        return np.array([]), np.array([])
    data = data - data.mean()
    window = np.hanning(len(data))
    amplitude = np.abs(np.fft.rfft(data * window)) * 2.0 / window.sum()
    freqs = np.fft.rfftfreq(len(data), d=tr.stats.delta)
    return freqs[1:], amplitude[1:]
```

- [ ] **Step 4: Run and commit**

Run: `uv run pytest tests/core/test_spectro.py -v` — Expected: all pass.

```bash
git add rs3d-app/src/rs3d/core/spectro.py rs3d-app/tests/core/test_spectro.py
git commit -m "feat(rs3d-app): amplitude spectrum for a single window

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Chart builders `helicorder_options` and `spectrum_options`

**Files:**
- Modify: `rs3d-app/src/rs3d/app/charts.py`
- Test: `rs3d-app/tests/app/test_charts.py`

**Interfaces:**
- Consumes: `rs3d.core.helicorder.Row`.
- Produces:
  - `ROW_PX = 14`, `ROW_COLORS = ("#37474f", "#ec407a")`
  - `helicorder_height_px(n_rows: int) -> int` — chart height so one row is exactly `ROW_PX` pixels (`n_rows * 14 + 8 + 36`)
  - `helicorder_options(rows: list[Row], scale: float, row_minutes: int = 30, click_every_s: float = 10.0) -> dict` — 48 line series named `row0..row47`, plus one scatter series named `"click"` whose points are `[x_minutes, row_index]`
  - `spectrum_options(freqs: np.ndarray, amplitude: np.ndarray) -> dict` — log–log single line

- [ ] **Step 1: Write the failing tests** (append to `tests/app/test_charts.py`)

```python
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
```

- [ ] **Step 2: Run and watch them fail**

Run: `uv run pytest tests/app/test_charts.py -k "helicorder or spectrum_options" -v` — Expected: FAIL `ImportError`.

- [ ] **Step 3: Implement** (append to `src/rs3d/app/charts.py`; add `import json` next to the other imports)

```python
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
                      "nameGap": 24, "interval": 5},
            "yAxis": [y_axis(utc_labels, "left"), y_axis(local_labels, "right")],
            "series": series}


def spectrum_options(freqs: np.ndarray, amplitude: np.ndarray) -> dict:
    """Log-log amplitude spectrum of one window."""
    data = [[float(f), float(a)] for f, a in zip(freqs, amplitude) if a > 0]
    return {"animation": False, "grid": {"left": 70, "right": 24, "top": 16, "bottom": 40},
            "xAxis": {"type": "log", "name": "Frequency in Hz", "nameLocation": "middle", "nameGap": 26},
            "yAxis": {"type": "log", "name": "Amplitude", "nameLocation": "middle", "nameGap": 52},
            "tooltip": {"trigger": "axis"},
            "series": [{"type": "line", "showSymbol": False, "data": data,
                        "lineStyle": {"width": 1, "color": "#e53935"}}]}
```

The existing import line `from datetime import datetime, timezone` is already at the top of `charts.py`; add only `import json`.

- [ ] **Step 4: Run and commit**

Run: `uv run pytest tests/app/test_charts.py -v && uv run pytest -q` — Expected: all pass.

```bash
git add rs3d-app/src/rs3d/app/charts.py rs3d-app/tests/app/test_charts.py
git commit -m "feat(rs3d-app): helicorder and spectrum chart builders

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Helicorder page and navigation

**Files:**
- Create: `rs3d-app/src/rs3d/app/pages/helicorder.py`
- Modify: `rs3d-app/src/rs3d/app/widgets.py` (add to `NAV`), `rs3d-app/src/rs3d/app/main.py` (register page), `rs3d-app/src/rs3d/help/en.toml` (labels)
- Test: `rs3d-app/tests/app/test_pages.py`

**Interfaces:**
- Consumes: `helicorder_options`, `helicorder_height_px` (Task 4); `load_day`, `build_rows`, `scale_for`, `click_to_time`, `ROW_MINUTES` (Task 2); `station_choices` from `rs3d.app.pages.data`; `state.data_prefs`, `state.store`, `state.paths.response`; `cached_inventory`, `get_inventory`.
- Produces: route `/helicorder?station=<net.sta.loc>&day=<YYYY-MM-DD>&channel=<EHZ>`; a module-level coroutine hook `pick(t: UTCDateTime)` that Task 6 replaces; helper `inventory_for(state, net, sta)` stays in this module until Task 6 moves it.

- [ ] **Step 1: Write the failing page tests** (append to `tests/app/test_pages.py`)

```python
def _write_day(tmp_path):
    """Ten minutes of EHZ on 2026-10-12 in the app's store."""
    import numpy as np
    from obspy import Trace, UTCDateTime
    from rs3d.core.store import Store
    tr = Trace(np.random.default_rng(0).integers(-500, 500, 60000).astype("int32"),
               header={"network": "AM", "station": "R77A7", "location": "00", "channel": "EHZ",
                       "sampling_rate": 100.0, "starttime": UTCDateTime("2026-10-12T00:00:00")})
    path = tmp_path / "10min.mseed"
    tr.write(str(path), format="MSEED")
    Store(tmp_path / "sds").import_file(path)


def test_helicorder_page_is_in_the_nav_and_shows_empty_message():
    async def scenario(user):
        await user.open("/helicorder")
        await user.should_see("Helicorder")
        await user.should_see("No data yet")
    run(scenario)


def test_helicorder_page_shows_requested_day_and_arrows_move_it(tmp_path):
    from nicegui import ui
    _write_day(tmp_path)

    async def scenario(user):
        await user.open("/helicorder?day=2026-10-12")
        await user.should_see("2026-10-12")
        user.find(marker="day-next").click()
        await user.should_see("2026-10-13")
        user.find(marker="day-prev").click()
        await user.should_see("2026-10-12")
    run(scenario)
```

- [ ] **Step 2: Run and watch them fail**

Run: `uv run pytest tests/app/test_pages.py -k helicorder -v`
Expected: FAIL (`Helicorder` not seen; route does not exist).

- [ ] **Step 3: Add labels, nav entry, registration**

`help/en.toml`: under `[labels.nav]` add `helicorder = "Helicorder"`; add a new section:

```toml
[labels.heli]
title = "Day view"
scale = "Scale"
previous_day = "Previous day"
next_day = "Next day"
picked = "Selected"
```

`app/widgets.py`: change `NAV` to
```python
NAV = (("status", "monitor_heart"), ("live", "show_chart"), ("helicorder", "graphic_eq"), ("data", "download"),
       ("guide", "menu_book"), ("settings", "settings"))
```

`app/main.py`: add `helicorder` to the import `from rs3d.app.pages import data, guide, helicorder, live, settings, status` and to the tuple `for page in (status, live, helicorder, data, guide, settings):`.

- [ ] **Step 4: Write the page**

```python
# src/rs3d/app/pages/helicorder.py
"""Helicorder page: one channel of one UTC day as 48 rows of 30 minutes; a click picks a time."""

from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import urlencode

from nicegui import run, ui
from obspy import UTCDateTime

from rs3d.app.charts import helicorder_height_px, helicorder_options
from rs3d.app.pages.data import station_choices
from rs3d.app.state import AppState
from rs3d.app.strings import label
from rs3d.app.widgets import frame
from rs3d.core.helicorder import ROW_MINUTES, build_rows, click_to_time, load_day, scale_for
from rs3d.core.response import cached_inventory, get_inventory

SCALES = {0.5: "0.5×", 1.0: "1×", 2.0: "2×", 4.0: "4×", 8.0: "8×"}


def inventory_for(state: AppState, net: str, sta: str):
    return cached_inventory(state.paths.response, net, sta) or get_inventory(state.paths.response, net, sta)


def parse_day(text: str | None, fallback: date) -> date:
    try:
        return date.fromisoformat(text) if text else fallback
    except ValueError:
        return fallback


def register(state: AppState) -> None:
    @ui.page("/helicorder")
    def helicorder_page(station: str | None = None, day: str | None = None, channel: str | None = None) -> None:
        device = frame(state, "helicorder")
        choices = station_choices(state, device)
        if not choices:
            ui.label(label("data.empty")).classes("text-grey-7")
            return
        remembered = state.data_prefs["station"]
        key = station if station in choices else (remembered if remembered in choices else choices[0])
        net, sta, loc = key.split(".")
        channels = tuple(state.store.channels(net, sta, loc))
        if not channels:
            ui.label(label("data.nothing")).classes("text-grey-7")
            return
        ch = channel if channel in channels else channels[0]
        days = state.store.days(net, sta, loc, ch)
        ctx = {"day": parse_day(day, max(days) if days else date.today())}

        def day_start() -> UTCDateTime:
            d = ctx["day"]
            return UTCDateTime(d.year, d.month, d.day)

        with ui.row().classes("items-center gap-2"):
            picker = ui.select(choices, value=key, label=label("data.station")).props("dense").classes("w-56")
            chan = ui.select(list(channels), value=ch).props("dense").classes("w-24")
            ui.button(icon="chevron_left", on_click=lambda: move(-1)).props("flat dense round") \
                .mark("day-prev").tooltip(label("heli.previous_day"))
            day_label = ui.label(ctx["day"].isoformat()).classes("font-mono")
            ui.button(icon="chevron_right", on_click=lambda: move(1)).props("flat dense round") \
                .mark("day-next").tooltip(label("heli.next_day"))
            prefs = state.data_prefs
            units = ui.toggle(["counts", "m/s"], value=prefs["units"]).props("dense no-caps")
            flt = ui.switch(label("data.filter"), value=prefs["filter"])
            scale = ui.select(SCALES, value=1.0, label=label("heli.scale")).props("dense").classes("w-24")

        message = ui.label("").classes("text-grey-7")
        chart = ui.echart({"series": []}).classes("w-full")

        def navigate(**changes) -> None:
            args = {"station": picker.value, "channel": chan.value, "day": ctx["day"].isoformat(), **changes}
            ui.navigate.to("/helicorder?" + urlencode(args))

        picker.on_value_change(lambda e: navigate(station=e.value, channel=""))
        chan.on_value_change(lambda e: navigate(channel=e.value))

        async def refresh() -> None:
            current = state.data_prefs
            band = (current["fmin"], current["fmax"]) if flt.value else None
            u = units.value
            start = day_start()

            def work():
                inv = inventory_for(state, net, sta) if u == "m/s" else None
                st = load_day(state.store, net, sta, loc, chan.value, ctx["day"], u, band, inv)
                rows = build_rows(st, start)
                return rows

            try:
                rows = await run.io_bound(work)
            except Exception as exc:  # e.g. no instrument response while offline
                ui.notify(str(exc), type="negative", multi_line=True)
                if u == "m/s":
                    units.value = "counts"  # triggers a new refresh in counts
                return
            day_label.text = ctx["day"].isoformat()
            if not any(len(r.values) for r in rows):
                message.text = label("data.nothing")
                chart.options.clear()
                chart.options.update({"series": []})
                chart.style("height: 0px")
                chart.update()
                return
            message.text = ""
            chart.options.clear()
            chart.options.update(helicorder_options(rows, scale_for(rows, float(scale.value))))
            chart.style(f"height: {helicorder_height_px(len(rows))}px")
            chart.update()

        def move(direction: int) -> None:
            ctx["day"] = ctx["day"] + timedelta(days=direction)
            ui.timer(0.01, refresh, once=True)
            day_label.text = ctx["day"].isoformat()

        async def pick(t: UTCDateTime) -> None:
            ui.notify(f"{label('heli.picked')}: {t.strftime('%Y-%m-%d %H:%M:%S')} UTC")

        async def on_click(e) -> None:
            if e.series_name != "click":
                return
            x_minutes, row = float(e.value[0]), int(round(float(e.value[1])))
            await pick(click_to_time(day_start(), ROW_MINUTES, row, x_minutes / ROW_MINUTES))

        chart.on_point_click(on_click)
        for control in (units, flt, scale):
            control.on_value_change(lambda _: ui.timer(0.01, refresh, once=True))
        ui.timer(0.1, refresh, once=True)
```

- [ ] **Step 5: Run the tests and the full suite**

Run: `uv run pytest tests/app/test_pages.py -v && uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Look at it once in a real browser, then commit**

Start the app on your data (`uv run rs3d-app --no-browser --port 8851`), import `data/AM.R77A7_*.mseed` on the Data page, open `/helicorder?day=2026-10-15`, and take a headless Chrome screenshot as in the earlier session. Expected: rows from about 00:25 to 07:09 draw, other rows empty, UTC hours on the left. Note anything that looks wrong and fix before committing.

```bash
git add rs3d-app/src rs3d-app/tests
git commit -m "feat(rs3d-app): helicorder page with day navigation

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: `DetailPanel` — zoom, shift, modes, filter, empty window

**Files:**
- Create: `rs3d-app/src/rs3d/app/detail.py`
- Modify: `rs3d-app/src/rs3d/app/pages/helicorder.py` (use the panel), `rs3d-app/src/rs3d/help/en.toml`
- Test: `rs3d-app/tests/app/test_detail.py`

**Interfaces:**
- Consumes: `waveform_options`, `set_stream_data`, `spectrogram_options`, `spectrum_options` (charts); `amplitude_spectrum`, `spectrogram`, `window_for` (core.spectro); `load_window`, `zoom_window`, `shift_window` (Task 2); `inventory_for` moves into `detail.py`.
- Produces:
  - `@dataclass(frozen=True) DetailContext(net, sta, loc, channel, units, band, use_utc)`
  - `detail_chart_options(mode: str, st: Stream, channel: str, use_utc: bool) -> dict | None` — `mode` is `"waveform" | "spectra" | "spectrogram"`; `None` when the stream has no samples for the channel
  - `class DetailPanel(state: AppState, get_ctx: Callable[[], DetailContext])` with `async open(center: UTCDateTime, span: float = 120.0)`, `close()`, attribute `.stream` (the loaded `Stream | None`); the clipboard button is added in Task 7

- [ ] **Step 1: Write the failing tests**

```python
# tests/app/test_detail.py
import numpy as np
from obspy import Stream, Trace, UTCDateTime

from rs3d.app.detail import detail_chart_options

T0 = UTCDateTime("2026-10-12T00:00:00")


def stream(seconds=120, channel="EHZ"):
    t = np.arange(0, seconds, 0.01)
    tr = Trace((1000 * np.sin(2 * np.pi * 5 * t)).astype("float64"), header={
        "network": "AM", "station": "R77A7", "location": "00", "channel": channel,
        "sampling_rate": 100.0, "starttime": T0})
    return Stream([tr])


def test_waveform_mode_is_a_line_chart_with_the_channel_name():
    opt = detail_chart_options("waveform", stream(), "EHZ", True)
    assert opt["series"][0]["name"] == "EHZ" and len(opt["series"][0]["data"]) > 100


def test_spectra_mode_is_log_log_and_peaks_near_5hz():
    opt = detail_chart_options("spectra", stream(), "EHZ", True)
    assert opt["xAxis"]["type"] == "log"
    data = opt["series"][0]["data"]
    assert abs(max(data, key=lambda p: p[1])[0] - 5.0) < 0.1


def test_spectrogram_mode_is_a_heatmap():
    opt = detail_chart_options("spectrogram", stream(), "EHZ", True)
    assert opt["series"][0]["type"] == "heatmap" and opt["series"][0]["data"]


def test_empty_window_or_other_channel_gives_none():
    assert detail_chart_options("waveform", Stream(), "EHZ", True) is None
    assert detail_chart_options("spectra", stream(channel="EHN"), "EHZ", True) is None
```

- [ ] **Step 2: Run and watch them fail**

Run: `uv run pytest tests/app/test_detail.py -v` — Expected: collection error `No module named 'rs3d.app.detail'`.

- [ ] **Step 3: Add labels** (`help/en.toml`)

```toml
[labels.detail]
waveform = "Waveform"
spectra = "Spectra"
spectrogram = "Spectrogram"
fit = "Fit"
zoom_in = "Zoom in"
zoom_out = "Zoom out"
earlier = "Earlier"
later = "Later"
no_window_data = "No data in this window."
```

- [ ] **Step 4: Write `detail.py`**

```python
# src/rs3d/app/detail.py
"""Detail view for a clicked time: waveform / spectra / spectrogram of about two minutes, with zoom and shift."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from nicegui import run, ui
from obspy import Stream, UTCDateTime

from rs3d.app import timeutil
from rs3d.app.charts import set_stream_data, spectrogram_options, spectrum_options, waveform_options
from rs3d.app.state import AppState
from rs3d.app.strings import label
from rs3d.core.helicorder import load_window, shift_window, zoom_window
from rs3d.core.response import cached_inventory, get_inventory
from rs3d.core.spectro import amplitude_spectrum, spectrogram, window_for

MODES = ("waveform", "spectra", "spectrogram")


@dataclass(frozen=True)
class DetailContext:
    net: str
    sta: str
    loc: str
    channel: str
    units: str
    band: tuple[float, float] | None
    use_utc: bool


def inventory_for(state: AppState, net: str, sta: str):
    return cached_inventory(state.paths.response, net, sta) or get_inventory(state.paths.response, net, sta)


def detail_chart_options(mode: str, st: Stream, channel: str, use_utc: bool) -> dict | None:
    """ECharts options for one detail mode, or None when the window has no samples for the channel."""
    traces = st.select(channel=channel)
    if not len(traces) or not sum(tr.stats.npts for tr in traces):
        return None
    if mode == "waveform":
        opt = waveform_options((channel,), use_utc)
        set_stream_data(opt, traces)
        return opt
    merged = traces.copy().merge(method=0)[0]
    if mode == "spectra":
        return spectrum_options(*amplitude_spectrum(merged))
    if mode == "spectrogram":
        return spectrogram_options(*spectrogram(merged, window_for(merged.stats.endtime - merged.stats.starttime)),
                                   use_utc=use_utc)
    raise ValueError(f"unknown mode {mode!r}")


class DetailPanel:
    """Hidden until `open()`. Loads its own data from the local archive."""

    def __init__(self, state: AppState, get_ctx: Callable[[], DetailContext]) -> None:
        self.state, self.get_ctx = state, get_ctx
        self.origin: tuple[UTCDateTime, UTCDateTime] | None = None
        self.window: tuple[UTCDateTime, UTCDateTime] | None = None
        self.mode = "waveform"
        self.stream: Stream | None = None
        with ui.card().classes("w-full") as self.card:
            with ui.row().classes("items-center gap-1"):
                self.title = ui.label("").classes("font-mono text-sm")
                ui.button(icon="fit_screen", on_click=self.fit).props("flat dense round") \
                    .tooltip(label("detail.fit")).mark("detail-fit")
                ui.button(icon="remove", on_click=lambda: self.zoom(2.0)).props("flat dense round") \
                    .tooltip(label("detail.zoom_out")).mark("detail-zoom-out")
                ui.button(icon="add", on_click=lambda: self.zoom(0.5)).props("flat dense round") \
                    .tooltip(label("detail.zoom_in")).mark("detail-zoom-in")
                ui.button(icon="chevron_left", on_click=lambda: self.shift(-1)).props("flat dense round") \
                    .tooltip(label("detail.earlier")).mark("detail-earlier")
                ui.button(icon="chevron_right", on_click=lambda: self.shift(1)).props("flat dense round") \
                    .tooltip(label("detail.later")).mark("detail-later")
                self.toggle = ui.toggle({m: label(f"detail.{m}") for m in MODES}, value="waveform",
                                        on_change=self.set_mode).props("dense no-caps")
                self.extra = ui.row().classes("items-center gap-1")  # clipboard button is added here (Task 7)
                ui.button(icon="close", on_click=self.close).props("flat dense round").mark("detail-close")
            self.message = ui.label("").classes("text-grey-7")
            self.chart = ui.echart({"series": []}).classes("w-full").style("height: 34vh")
        self.card.set_visibility(False)

    async def open(self, center: UTCDateTime, span: float = 120.0) -> None:
        self.origin = (center - span / 2, center + span / 2)
        self.window = self.origin
        self.card.set_visibility(True)
        await self.reload()

    def close(self) -> None:
        self.card.set_visibility(False)

    async def fit(self) -> None:
        if self.origin:
            self.window = self.origin
            await self.reload()

    async def zoom(self, factor: float) -> None:
        if self.window:
            self.window = zoom_window(*self.window, factor)
            await self.reload()

    async def shift(self, direction: int) -> None:
        if self.window:
            self.window = shift_window(*self.window, direction)
            await self.reload()

    def set_mode(self, _=None) -> None:
        self.mode = self.toggle.value
        self.draw()

    async def reload(self) -> None:
        if self.window is None:
            return
        ctx, (a, b) = self.get_ctx(), self.window

        def work() -> Stream:
            inv = inventory_for(self.state, ctx.net, ctx.sta) if ctx.units == "m/s" else None
            return load_window(self.state.store, ctx.net, ctx.sta, ctx.loc, ctx.channel, a, b,
                               ctx.units, ctx.band, inv)

        try:
            self.stream = await run.io_bound(work)
        except Exception as exc:
            ui.notify(str(exc), type="negative", multi_line=True)
            return
        self.draw()

    def draw(self) -> None:
        if self.window is None or self.stream is None:
            return
        ctx = self.get_ctx()
        a, b = self.window
        self.title.text = (f"{ctx.net}.{ctx.sta}.{ctx.loc}.{ctx.channel}  "
                           f"{timeutil.to_text(a, not ctx.use_utc)} → {timeutil.to_text(b, not ctx.use_utc)}")
        options = detail_chart_options(self.mode, self.stream, ctx.channel, ctx.use_utc)
        if options is None:
            self.message.text = label("detail.no_window_data")
            self.chart.set_visibility(False)
            return
        self.message.text = ""
        self.chart.set_visibility(True)
        self.chart.options.clear()
        self.chart.options.update(options)
        self.chart.update()
```

- [ ] **Step 5: Run the unit tests**

Run: `uv run pytest tests/app/test_detail.py -v` — Expected: all pass.

- [ ] **Step 6: Wire the panel into the page**

In `pages/helicorder.py`: delete `inventory_for` (now in `detail.py`) and import it: `from rs3d.app.detail import DetailContext, DetailPanel, inventory_for`. Create the panel above the chart and replace the `pick` stub:

```python
        def detail_ctx() -> DetailContext:
            current = state.data_prefs
            band = (current["fmin"], current["fmax"]) if flt.value else None
            return DetailContext(net, sta, loc, chan.value, units.value, band, not state.use_local_time)

        detail = DetailPanel(state, detail_ctx)
```
(place this right after `message = ui.label(...)` and before `chart = ui.echart(...)`), and:

```python
        async def pick(t: UTCDateTime) -> None:
            await detail.open(t)
```
Remove the unused `label('heli.picked')` string use.

- [ ] **Step 7: Page test for the empty-window case, run all, commit**

Add to `tests/app/test_detail.py` (pins Review Focus item 1 at the panel level):

```python
def test_panel_message_for_a_window_with_no_data():
    from rs3d.app.detail import detail_chart_options
    empty = Stream([Trace(np.zeros(0), header={"channel": "EHZ", "sampling_rate": 100.0, "starttime": T0})])
    assert detail_chart_options("waveform", empty, "EHZ", True) is None
```

Run: `uv run pytest -q` — Expected: all pass.

```bash
git add rs3d-app/src rs3d-app/tests
git commit -m "feat(rs3d-app): detail view with zoom, shift, spectra and spectrogram

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Waveform Clipboard (dialog + PNG)

**Files:**
- Modify: `rs3d-app/src/rs3d/core/export.py`, `rs3d-app/src/rs3d/app/detail.py`, `rs3d-app/src/rs3d/help/en.toml`
- Test: `rs3d-app/tests/core/test_export.py`, `rs3d-app/tests/app/test_detail.py`

**Interfaces:**
- Consumes: `amplitude_spectrum`, `spectrogram`, `window_for` (core.spectro); `DetailPanel.stream`, `DetailPanel.extra`, `DetailContext` (Task 6).
- Produces:
  - `clipboard_title(net, sta, loc, channel, start, end, units, band) -> str`
  - `write_clipboard_png(st: Stream, path: Path, title: str, ylabel: str = "amplitude") -> Path` — waveform, spectrogram and spectrum stacked; raises `ValueError("no data")` for an empty stream
  - `DetailPanel.open_clipboard()` — dialog with three stacked charts, a camera button (`data-testid=camera`) that downloads the PNG, and a close button; the toolbar button has `data-testid=clipboard`

- [ ] **Step 1: Write the failing tests** (append to `tests/core/test_export.py`)

```python
def test_clipboard_title_states_station_channel_range_units_and_filter():
    from obspy import UTCDateTime
    from rs3d.core.export import clipboard_title
    t = clipboard_title("AM", "R77A7", "00", "EHZ", UTCDateTime("2026-10-12T00:00:00"),
                        UTCDateTime("2026-10-12T00:02:00"), "m/s", (1.0, 10.0))
    assert t == "AM.R77A7.00.EHZ  2026-10-12 00:00:00 → 00:02:00 UTC  m/s  band-pass 1–10 Hz"
    assert clipboard_title("AM", "R77A7", "00", "EHZ", UTCDateTime("2026-10-12T00:00:00"),
                           UTCDateTime("2026-10-12T00:02:00"), "counts", None).endswith("counts")


def test_clipboard_png_is_a_real_non_blank_image(tmp_path):
    import numpy as np
    from matplotlib import image
    from obspy import Stream, Trace, UTCDateTime
    from rs3d.core.export import write_clipboard_png
    t = np.arange(0, 60, 0.01)
    st = Stream([Trace(1000 * np.sin(2 * np.pi * 5 * t), header={
        "network": "AM", "station": "R77A7", "location": "00", "channel": "EHZ", "sampling_rate": 100.0,
        "starttime": UTCDateTime("2026-10-12T00:00:00")})])
    out = write_clipboard_png(st, tmp_path / "clip.png", "title")
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    img = image.imread(out)
    assert img.shape[0] > 500 and (img[..., :3] < 0.9).mean() > 0.02


def test_clipboard_png_refuses_an_empty_stream(tmp_path):
    import pytest
    from obspy import Stream
    from rs3d.core.export import write_clipboard_png
    with pytest.raises(ValueError, match="no data"):
        write_clipboard_png(Stream(), tmp_path / "x.png", "t")
```

- [ ] **Step 2: Run and watch them fail**

Run: `uv run pytest tests/core/test_export.py -k clipboard -v` — Expected: FAIL `ImportError`.

- [ ] **Step 3: Implement the core** (append to `src/rs3d/core/export.py`)

```python
def clipboard_title(net: str, sta: str, loc: str, channel: str, start, end, units: str,
                    band: tuple[float, float] | None) -> str:
    text = (f"{net}.{sta}.{loc}.{channel}  {start.strftime('%Y-%m-%d %H:%M:%S')} → "
            f"{end.strftime('%H:%M:%S')} UTC  {units}")
    if band is not None:
        text += f"  band-pass {band[0]:g}–{band[1]:g} Hz"
    return text


def write_clipboard_png(st: Stream, path: Path, title: str, ylabel: str = "amplitude") -> Path:
    """Waveform, spectrogram and amplitude spectrum of the first channel, stacked, as one PNG."""
    if not len(st):
        raise ValueError("no data")
    import matplotlib.pyplot as plt

    from rs3d.core.spectro import amplitude_spectrum, spectrogram, window_for

    tr = st.copy().merge(method=0)[0]
    data = np.ma.filled(tr.data.astype(float), np.nan)
    t = np.arange(tr.stats.npts) / tr.stats.sampling_rate
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 9), constrained_layout=True)
    ax1.plot(t, data, lw=0.6, color="#444444")
    ax1.set_xlim(0, t[-1] if len(t) else 1)
    ax1.set_ylabel(ylabel)
    times, freqs, db = spectrogram(tr, window_for(tr.stats.endtime - tr.stats.starttime))
    ax2.pcolormesh(times - tr.stats.starttime.timestamp, freqs, db, shading="auto", cmap="inferno")
    ax2.set_xlim(0, t[-1] if len(t) else 1)
    ax2.set_ylabel("f in Hz")
    f, a = amplitude_spectrum(tr)
    if len(f):
        ax3.loglog(f, a, color="#e53935", lw=0.8)
    ax3.set_xlabel("Frequency in Hz")
    ax3.set_ylabel("Amplitude")
    ax3.grid(True, which="both", alpha=0.3)
    fig.suptitle(title)
    fig.savefig(str(path), dpi=100)
    plt.close(fig)
    return path
```

- [ ] **Step 4: Run and watch them pass**

Run: `uv run pytest tests/core/test_export.py -v` — Expected: all pass.

- [ ] **Step 5: Add the dialog** — labels in `help/en.toml`:

```toml
[labels.clipboard]
title = "Waveform Clipboard"
camera = "Save picture"
```

In `app/detail.py` add imports `import tempfile`, `from pathlib import Path`, and `from rs3d.core.export import clipboard_title, write_clipboard_png`. In `DetailPanel.__init__`, replace the `self.extra = ...` line with the real button:

```python
                ui.button(icon="content_paste", on_click=self.open_clipboard).props(
                    "flat dense round data-testid=clipboard").tooltip(label("clipboard.title"))
```
Add this method to the class:

```python
    def open_clipboard(self) -> None:
        """Dialog with waveform, spectrogram and spectrum of the current window; the camera saves a PNG."""
        if self.stream is None or self.window is None:
            return
        ctx, (a, b) = self.get_ctx(), self.window
        st = self.stream.select(channel=ctx.channel)
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-6xl"):
            with ui.row().classes("items-center w-full"):
                ui.label(label("clipboard.title")).classes("text-lg font-bold")
                ui.space()

                async def save() -> None:
                    title = clipboard_title(ctx.net, ctx.sta, ctx.loc, ctx.channel, a, b, ctx.units, ctx.band)
                    out = Path(tempfile.mkdtemp()) / f"{ctx.net}.{ctx.sta}.{ctx.channel}_{a.strftime('%Y%m%dT%H%M%S')}.png"
                    await run.io_bound(write_clipboard_png, st, out, title, ctx.units)
                    ui.download.file(out, out.name)

                ui.button(icon="photo_camera", on_click=save).props("flat round data-testid=camera") \
                    .tooltip(label("clipboard.camera"))
                ui.button(icon="close", on_click=dialog.close).props("flat round")
            for mode, height in (("waveform", "22vh"), ("spectrogram", "26vh"), ("spectra", "26vh")):
                options = detail_chart_options(mode, st, ctx.channel, ctx.use_utc)
                if options is None:
                    ui.label(label("detail.no_window_data")).classes("text-grey-7")
                    break
                ui.echart(options).classes("w-full").style(f"height: {height}")
        dialog.open()
```
Remove the temporary `self.extra` row if present.

- [ ] **Step 6: Add a panel-level test, run everything, commit**

Add to `tests/app/test_detail.py`:

```python
def test_clipboard_panels_use_the_same_option_builders():
    st = stream()
    for mode, kind in (("waveform", "line"), ("spectrogram", "heatmap"), ("spectra", "line")):
        assert detail_chart_options(mode, st, "EHZ", True)["series"][0]["type"] == kind
```

Run: `uv run pytest -q` — Expected: all pass.

```bash
git add rs3d-app/src rs3d-app/tests
git commit -m "feat(rs3d-app): waveform clipboard dialog with PNG download

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Real-browser test, mutation check, README

**Files:**
- Create: `rs3d-app/tests/e2e/test_helicorder_flow.py`
- Modify: `rs3d-app/README.md`

**Interfaces:**
- Consumes: the page (`/helicorder`), `data-testid=clipboard`, `data-testid=camera`, the `Spectrogram` toggle label, the existing e2e fixtures `server` and the `mseed` pattern from `tests/e2e/test_data_flow.py`.
- Produces: one end-to-end test and README documentation.

- [ ] **Step 1: Write the test**

```python
# tests/e2e/test_helicorder_flow.py
"""Real-browser test: helicorder -> click a row -> detail view -> spectrogram -> clipboard -> PNG download.

Run with:  uv run pytest -m e2e
"""

import numpy as np
import pytest
from matplotlib import image
from obspy import Trace, UTCDateTime

from tests.e2e.test_data_flow import PAINTED, playwright_sync, server  # noqa: F401  (fixture re-export)

pytestmark = pytest.mark.e2e


@pytest.fixture
def three_hours(tmp_path):
    """3 h of EHZ at 100 Hz: noise plus a 5 Hz burst at minute 70, starting 2026-10-12 00:00 UTC."""
    rng = np.random.default_rng(2)
    n = 3 * 3600 * 100
    data = rng.normal(0, 100, n)
    data[70 * 6000:70 * 6000 + 3000] += 3000 * np.sin(2 * np.pi * 5 * np.arange(3000) / 100)
    tr = Trace(data.astype("int32"), header={"network": "AM", "station": "R77A7", "location": "00",
                                           "channel": "EHZ", "sampling_rate": 100.0,
                                           "starttime": UTCDateTime("2026-10-12T00:00:00")})
    path = tmp_path / "AM.R77A7.mseed"
    tr.write(str(path), format="MSEED")
    return path


def test_click_a_row_and_save_the_clipboard(server, three_hours, tmp_path):  # noqa: F811
    with playwright_sync.sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000}, accept_downloads=True)
        page.goto(server + "/data")
        page.locator("input[type=file]").set_input_files(str(three_hours))
        page.get_by_text("Preview", exact=True).wait_for(timeout=30000)
        page.goto(server + "/helicorder?station=AM.R77A7.00&day=2026-10-12")
        chart = page.locator(".nicegui-echart").first
        page.wait_for_function("document.querySelector('.nicegui-echart canvas')?.height > 600", timeout=30000)
        page.wait_for_timeout(1500)
        box = chart.bounding_box()
        # grid: left 56, right 56, top 8, bottom 36; row 2 (01:00-01:30), x = 10 min of 30
        x = box["x"] + 56 + (box["width"] - 112) * (10 / 30)
        y = box["y"] + 8 + 14 * (2 + 0.5)
        page.mouse.click(x, y)
        page.get_by_text("Spectrogram", exact=True).wait_for(timeout=15000)
        title = page.locator(".font-mono").filter(has_text="AM.R77A7.00.EHZ").first.inner_text()
        assert "2026-10-12 01:10:" in title or "2026-10-12 01:09:" in title, title  # window centred on 01:10
        page.get_by_text("Spectrogram", exact=True).click()
        page.wait_for_timeout(1500)
        painted = page.locator(".nicegui-echart canvas").evaluate_all(
            "cs => cs.filter(c => c.offsetParent).map(" + PAINTED.replace("canvas =>", "canvas =>") + ")")
        assert painted and max(painted) > 500, painted
        page.locator("[data-testid=clipboard]").click()
        with page.expect_download(timeout=30000) as dl:
            page.locator("[data-testid=camera]").click()
        out = tmp_path / "clip.png"
        dl.value.save_as(str(out))
        browser.close()
    img = image.imread(out)
    assert img.shape[0] > 500 and (img[..., :3] < 0.9).mean() > 0.02
```

Note for the implementer: the `evaluate_all` string composition is fiddly. If it fails to evaluate, replace it with a loop in Python: `for i in range(canvases.count()): if canvases.nth(i).is_visible(): painted.append(canvases.nth(i).evaluate(PAINTED))`.

- [ ] **Step 2: Run it**

Run: `uv run pytest -m e2e tests/e2e/test_helicorder_flow.py -v`
Expected: PASS. If it fails, read the assertion and the screenshot of the page (add a temporary `page.screenshot`) before changing anything; fix the product code or the click coordinates, not by loosening assertions.

- [ ] **Step 3: Mutation check — prove the test can fail**

Temporarily change `ROW_PX = 14` to `ROW_PX = 20` in `app/charts.py` only (the test still clicks at 14 px rows).
Run: `uv run pytest -m e2e tests/e2e/test_helicorder_flow.py -v` — Expected: FAIL (wrong row or the title assertion).
Revert: `git checkout rs3d-app/src/rs3d/app/charts.py`. Re-run — Expected: PASS.

- [ ] **Step 4: README**

In `rs3d-app/README.md` add a row to the page table:

```markdown
| **Helicorder** | 24-hour day view, one row per 30 minutes. Click a row to open a ~2 minute detail view (waveform, spectra, spectrogram, zoom, band-pass) and save a Waveform Clipboard picture. Uses the data already on the laptop. |
```
and mention `Helicorder` in the "Using it without a Shake" paragraph ("everything on the Data and Helicorder pages works on it").

- [ ] **Step 5: Full run and commit**

Run: `uv run pytest -q && uv run pytest -m e2e -q` — Expected: all pass (unit/page suite and both browser tests).

```bash
git add rs3d-app/tests/e2e/test_helicorder_flow.py rs3d-app/README.md
git commit -m "test(rs3d-app): browser test for helicorder click, detail view and clipboard

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage:** page and navigation → Task 5; `core/helicorder.py` rows/scale/click_to_time → Task 2; chart builders → Task 4; click spike → Task 1; detail view controls (fit, zoom, shift, modes, close) and `amplitude_spectrum` → Tasks 3 and 6; clipboard and camera → Task 7; error handling (no data, no response, short fragments) → Tasks 2, 5, 6; testing section → Tasks 2–8.

**Filter control:** the spec's detail-view Filter control is the helicorder page's Band-pass switch (one source of truth); the panel reads it through `get_ctx()` on every reload, and changing the switch redraws the helicorder. The spec now says so.

**Placeholder scan:** none ("TBD", "similar to", "handle edge cases" absent); every code step has code. One implementer note (the `evaluate_all` composition in Task 8) gives an explicit simpler alternative.

**Type consistency:** `Row(start, seconds, values)`, `build_rows(st, day_start, row_minutes, points)`, `scale_for(rows, factor)`, `click_to_time(day_start, row_minutes, row_index, x_fraction)`, `zoom_window/shift_window`, `load_day/load_window`, `DetailContext(net, sta, loc, channel, units, band, use_utc)`, `detail_chart_options(mode, st, channel, use_utc)` are used with the same names and argument order in every task. `inventory_for` moves from the page (Task 5) to `detail.py` (Task 6) and the page imports it from there.
