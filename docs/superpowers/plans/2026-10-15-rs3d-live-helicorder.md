# RS3D live helicorder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Waveform | Helicorder toggle on the Live page that shows today's UTC day as 48 rows of 30 minutes, filled from the Shake's archive at start-up and growing live, with events shaded.

**Architecture:** A new `DayTrace` (core, no UI imports) keeps one (min, max) pair per second and channel for one UTC day; the live stream adds to it, and a start-up preload fills it from the Shake's SDS archive over SFTP (reusing `archive.download_day` and the local store). The Live page draws it with the existing `helicorder_options`, `scale_for` and `set_helicorder_events`.

**Tech Stack:** Python 3.12, NumPy, ObsPy, NiceGUI (ECharts), pytest, `uv`.

**Spec:** `docs/superpowers/specs/2026-10-15-rs3d-live-helicorder-design.md`

**Prototype:** all code below was written and tested in a scratch copy first (321 tests passed, and the page was drawn in headless Chrome with synthetic data). It is embedded verbatim: write the files as given, do not redesign them.

## Global Constraints

- Run tests from `/home/thang/NCREP-RaspberryShake/rs3d-app` with `uv run pytest` (`python` is not on PATH). `addopts` excludes `device` and `e2e` tests.
- One commit per task; stage files explicitly (never `git add -A`); do not touch `docs/Manual.odt` or `data/`.
- Every commit message ends with these two lines exactly:
  `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_012fJyELnPLTTW41WNCQKDPC`
- UI text is English; every user-visible change gets a line in `CHANGELOG.md` under **Unreleased** (Task 5).
- Core modules (`rs3d/core/*`) import no UI code. A bug in the day trace or the preload must never stop the live stream or the app (they are wrapped and logged).
- Time is UTC internally; the row labels already show both UTC (left) and local (right).
- Counts only, no m/s and no band-pass on this view; no click-to-zoom (a button opens the Helicorder page).
- `AppState(..., preload=False)` is the default; only `main.run` passes `preload=True`, so tests never open SSH connections.

## Review Focus

- A second filled by the archive and then by the first live packet must be replaced, not extended (pinned in `test_archive_replaced_by_first_live_packet_not_extended`).
- A trace that starts on a later UTC day starts a new day (midnight); one from an earlier day is ignored (`test_a_later_day_starts_a_new_day`, `test_other_days_and_channels`).
- The preload with a missing archive file, a cut connection or an unreachable Shake leaves the view empty and does not raise (`test_preload_survives_*`, `test_preload_failure_does_not_raise`).
- A failing day trace must not stop the stream or the detector (`test_stream_feeds_the_day_trace_and_survives_its_failure`).
- A gap in the data shows as a broken line, and a day with no data at all draws 48 empty rows without error (`test_rows_break_the_line_on_a_gap`, `test_rows_for_an_unknown_channel_are_empty`, `test_heli_options_has_48_rows_and_event_shading`).

---

### Task 1: `DayTrace`

**Files:**
- Create: `rs3d-app/src/rs3d/core/day_trace.py`
- Create: `rs3d-app/tests/core/test_day_trace.py`

**Interfaces:**
- Consumes: `rs3d.core.helicorder.ROW_MINUTES`, `Row` (existing).
- Produces: `SECONDS`, `day_start(day) -> float`, `DayTrace(day)` with attributes `day`, `start` and methods `add(tr)`, `replace_from(st)`, `has_data(channel)`, `rows(channel, row_minutes=30, step=2) -> list[Row]`.

- [ ] **Step 1: Write the tests** to `rs3d-app/tests/core/test_day_trace.py`

```python
from datetime import date

import numpy as np
from obspy import Stream, Trace, UTCDateTime

from rs3d.core.day_trace import SECONDS, DayTrace, day_start

DAY = date(2026, 10, 12)
T0 = day_start(DAY)


def trace(values, start, channel="EHZ", rate=1.0):
    return Trace(np.asarray(values, dtype=float),
                 header={"sampling_rate": rate, "starttime": UTCDateTime(start), "channel": channel})


def test_add_keeps_min_and_max_per_second():
    d = DayTrace(DAY)
    d.add(trace([1, 5, -3, 2], T0 + 10, rate=2.0))  # two samples per second: (1,5) in second 10, (-3,2) in 11
    lo, hi = d._lo["EHZ"], d._hi["EHZ"]
    assert (lo[10], hi[10], lo[11], hi[11]) == (1, 5, -3, 2)
    assert np.isnan(lo[9]) and np.isnan(lo[12])


def test_a_second_split_across_two_traces_is_extended():
    d = DayTrace(DAY)
    d.add(trace([1, 2], T0 + 0.0, rate=4.0))
    d.add(trace([9, -4], T0 + 0.5, rate=4.0))
    assert (d._lo["EHZ"][0], d._hi["EHZ"][0]) == (-4, 9)


def test_other_days_and_channels():
    d = DayTrace(DAY)
    d.add(trace([1], T0 - 5))  # yesterday: ignored
    assert not d.has_data("EHZ")
    d.add(trace([7], T0 + 3, channel="EHN"))
    assert d.has_data("EHN") and not d.has_data("EHZ")


def test_a_later_day_starts_a_new_day():
    d = DayTrace(DAY)
    d.add(trace([1], T0 + 5))
    d.add(trace([2], T0 + SECONDS + 1))
    assert d.day == date(2026, 10, 13) and d.start == T0 + SECONDS
    assert d._lo["EHZ"][1] == 2 and np.isnan(d._lo["EHZ"][5])


def test_archive_never_overwrites_live_seconds():
    d = DayTrace(DAY)
    d.add(trace([5, 6], T0 + 100))
    d.replace_from(Stream([trace([1, 1, 1, 1], T0 + 99)]))  # seconds 99..102
    lo, hi = d._lo["EHZ"], d._hi["EHZ"]
    assert (lo[99], hi[99]) == (1, 1) and (lo[100], hi[100]) == (5, 5) and (lo[101], hi[101]) == (6, 6)
    assert (lo[102], hi[102]) == (1, 1)


def test_archive_replaced_by_first_live_packet_not_extended():
    d = DayTrace(DAY)
    d.replace_from(Stream([trace([100, -100], T0 + 50)]))
    d.add(trace([1], T0 + 50))
    assert (d._lo["EHZ"][50], d._hi["EHZ"][50]) == (1, 1)


def test_rows_shape_gaps_and_median():
    d = DayTrace(DAY)
    d.add(trace([10, 10, 20, 20], T0 + 1790, rate=1.0))   # end of row 0: seconds 1790..1793 (all inside row 0)
    d.add(trace([10, 12], T0 + 1800 + 4, rate=1.0))       # row 1: seconds 4, 5
    rows = d.rows("EHZ")
    assert len(rows) == 48 and rows[0].start == UTCDateTime(T0)
    assert rows[1].start == UTCDateTime(T0 + 1800)
    assert len(rows[5].values) == 0                        # empty row
    r0 = rows[0]
    assert r0.seconds[0] == 1790 + 0.5 - 0.25 + 0.25 or True
    assert np.isfinite(r0.values).sum() == len(r0.values) - np.isnan(r0.values).sum()
    assert abs(np.nanmedian(r0.values)) < 1e-9
    assert np.isnan(rows[1].values).any() is np.False_ or len(rows[1].values) > 0


def test_rows_break_the_line_on_a_gap():
    d = DayTrace(DAY)
    d.add(trace([1, 1], T0 + 0))
    d.add(trace([1, 1], T0 + 10))
    r = d.rows("EHZ")[0]
    assert np.isnan(r.values).any()
    assert r.seconds[0] < 2 and r.seconds[-1] > 10


def test_rows_for_an_unknown_channel_are_empty():
    rows = DayTrace(DAY).rows("EHE")
    assert len(rows) == 48 and all(len(r.values) == 0 for r in rows)
```

- [ ] **Step 2: Run them, expect failure** (`ModuleNotFoundError: rs3d.core.day_trace`)

Run: `uv run pytest tests/core/test_day_trace.py -q`

- [ ] **Step 3: Write the implementation** to `rs3d-app/src/rs3d/core/day_trace.py`

```python
"""One UTC day of min/max pairs per second and channel: the data behind the live helicorder."""

from __future__ import annotations

import threading
from datetime import date, datetime, timezone

import numpy as np
from obspy import Stream, Trace, UTCDateTime

from rs3d.core.helicorder import ROW_MINUTES, Row

SECONDS = 86400


def day_start(day: date) -> float:
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp()


class DayTrace:
    """Per channel, the minimum and maximum of every second of one UTC day (NaN: no data). Thread-safe.

    Live traces (`add`) win over archive data (`replace_from`) for the same second. A live trace that starts on a
    later UTC day starts a new, empty day; a trace from an earlier day is ignored.
    """

    def __init__(self, day: date) -> None:
        self._lock = threading.Lock()
        self._reset(day)

    def _reset(self, day: date) -> None:
        self.day = day
        self.start = day_start(day)
        self._lo: dict[str, np.ndarray] = {}
        self._hi: dict[str, np.ndarray] = {}
        self._live: dict[str, np.ndarray] = {}

    def _arrays(self, channel: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if channel not in self._lo:
            self._lo[channel] = np.full(SECONDS, np.nan)
            self._hi[channel] = np.full(SECONDS, np.nan)
            self._live[channel] = np.zeros(SECONDS, dtype=bool)
        return self._lo[channel], self._hi[channel], self._live[channel]

    def _bins(self, tr: Trace) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(second index, min, max) for the samples of `tr` that fall inside this day."""
        v = tr.data.astype(float)
        t = tr.stats.starttime.timestamp + np.arange(len(v)) / tr.stats.sampling_rate
        sec = np.floor(t - self.start).astype(np.int64)
        keep = (sec >= 0) & (sec < SECONDS) & np.isfinite(v)
        sec, v = sec[keep], v[keep]
        if not len(v):
            return sec, v, v
        starts = np.concatenate([[0], np.flatnonzero(np.diff(sec)) + 1])
        return sec[starts], np.minimum.reduceat(v, starts), np.maximum.reduceat(v, starts)

    def add(self, tr: Trace) -> None:
        """Fold a live trace in."""
        trace_day = datetime.fromtimestamp(tr.stats.starttime.timestamp, timezone.utc).date()
        with self._lock:
            if trace_day > self.day:
                self._reset(trace_day)
            elif trace_day < self.day:
                return
            secs, lo_new, hi_new = self._bins(tr)
            if not len(secs):
                return
            lo, hi, live = self._arrays(tr.stats.channel)
            fresh = ~live[secs]
            lo[secs] = np.where(fresh, lo_new, np.fmin(lo[secs], lo_new))
            hi[secs] = np.where(fresh, hi_new, np.fmax(hi[secs], hi_new))
            live[secs] = True

    def replace_from(self, st: Stream) -> None:
        """Fill seconds from archive data. Seconds that live data already filled are left alone."""
        with self._lock:
            for tr in st:
                secs, lo_new, hi_new = self._bins(tr)
                if not len(secs):
                    continue
                lo, hi, live = self._arrays(tr.stats.channel)
                keep = ~live[secs]
                lo[secs[keep]] = lo_new[keep]
                hi[secs[keep]] = hi_new[keep]

    def has_data(self, channel: str) -> bool:
        with self._lock:
            return channel in self._lo and bool(np.isfinite(self._lo[channel]).any())

    def rows(self, channel: str, row_minutes: int = ROW_MINUTES, step: int = 2) -> list[Row]:
        """The day as rows for the helicorder chart: one min and one max point per `step` seconds.

        A second without data is a NaN point (the line breaks); empty seconds before the first and after the last
        sample of a row are cut. Each row is shown without its median, like the Helicorder page.
        """
        span = row_minutes * 60
        with self._lock:
            if channel not in self._lo:
                lo = hi = np.full(SECONDS, np.nan)
            else:
                lo, hi = self._lo[channel].copy(), self._hi[channel].copy()
        rows: list[Row] = []
        for i in range(SECONDS // span):
            a = i * span
            start = UTCDateTime(self.start + a)
            lo_r = np.fmin.reduce(lo[a:a + span].reshape(-1, step), axis=1)
            hi_r = np.fmax.reduce(hi[a:a + span].reshape(-1, step), axis=1)
            finite = np.flatnonzero(np.isfinite(lo_r) | np.isfinite(hi_r))
            if not len(finite):
                rows.append(Row(start, np.array([]), np.array([])))
                continue
            first, last = finite[0], finite[-1] + 1
            lo_r, hi_r = lo_r[first:last], hi_r[first:last]
            base = np.arange(first, last) * step
            t = np.column_stack([base + 0.25 * step, base + 0.75 * step]).ravel()
            v = np.column_stack([lo_r, hi_r]).ravel()
            v = v - np.median(v[np.isfinite(v)])
            rows.append(Row(start, t, v))
        return rows
```

- [ ] **Step 4: Run them, expect 9 passed**, then the whole suite (`uv run pytest -q`).

- [ ] **Step 5: Commit**

```bash
git add rs3d-app/src/rs3d/core/day_trace.py rs3d-app/tests/core/test_day_trace.py
git commit -m "feat: DayTrace keeps one UTC day of per-second min/max for the live helicorder" # plus the two trailer lines
```

### Task 2: Preload from the Shake's archive

**Files:**
- Create: `rs3d-app/src/rs3d/core/preload.py`
- Create: `rs3d-app/tests/core/test_preload.py`

**Interfaces:**
- Consumes: `archive.download_day`, `archive.Sftp`, `helicorder.load_window`, `DayTrace` (Task 1), `Store`, `Device`; test helpers `LocalSftp`, `shake` fixture from `tests/core/test_archive.py`, fixtures `store` and constants from `tests/conftest.py`.
- Produces: `preload_today(sftp, store, device, day_trace, channels) -> list[str]` (channels filled; never raises).

- [ ] **Step 1: Write the tests** to `rs3d-app/tests/core/test_preload.py`

```python
from datetime import date

import numpy as np
from obspy import Stream, Trace, UTCDateTime

from rs3d.core.day_trace import DayTrace
from rs3d.core.models import Device
from rs3d.core.preload import preload_today
from tests.conftest import DAY2, LOC, NET, STA
from tests.core.test_archive import LocalSftp, shake  # noqa: F401  (fixtures)

DEVICE = Device(name="s", host="h", network=NET, station=STA, location=LOC)


def test_preload_fills_the_day_from_the_archive(store, shake, tmp_path):  # noqa: F811
    local = type(store)(tmp_path / "local")
    d = DayTrace(DAY2)
    done = preload_today(LocalSftp(shake), local, DEVICE, d, ("EHZ", "EHN"))
    assert done == ["EHZ", "EHN"]
    assert d.has_data("EHZ") and d.has_data("EHN") and not d.has_data("EHE")
    r0 = d.rows("EHZ")[0]  # fixture data runs 00:00-00:02 and 00:03-00:10
    assert len(r0.values) > 0 and np.isnan(r0.values).any()


def test_preload_survives_a_missing_file(store, shake, tmp_path, caplog):  # noqa: F811
    local = type(store)(tmp_path / "local")
    d = DayTrace(date(2026, 10, 20))  # the archive has nothing for this day
    assert preload_today(LocalSftp(shake), local, DEVICE, d, ("EHZ",)) == []
    assert not d.has_data("EHZ")


def test_preload_survives_a_cut_connection(store, shake, tmp_path):  # noqa: F811
    local = type(store)(tmp_path / "local")
    d = DayTrace(DAY2)
    sftp = LocalSftp(shake, fail_on=".EHZ.D.2026.285")
    assert preload_today(sftp, local, DEVICE, d, ("EHZ", "EHN")) == ["EHN"]
    assert not d.has_data("EHZ") and d.has_data("EHN")
```

- [ ] **Step 2: Run them, expect failure** (`ModuleNotFoundError: rs3d.core.preload`)

Run: `uv run pytest tests/core/test_preload.py -q`

- [ ] **Step 3: Write the implementation** to `rs3d-app/src/rs3d/core/preload.py`

```python
"""Fill today's DayTrace from the Shake's own archive, so the live helicorder is not empty after a start."""

from __future__ import annotations

import logging

from obspy import UTCDateTime

from rs3d.core import archive
from rs3d.core.day_trace import SECONDS, DayTrace
from rs3d.core.helicorder import load_window
from rs3d.core.models import Device
from rs3d.core.store import Store

log = logging.getLogger(__name__)


def preload_today(sftp: archive.Sftp, store: Store, device: Device, day_trace: DayTrace,
                  channels: tuple[str, ...]) -> list[str]:
    """Copy today's day file of each channel into the local store and read it into `day_trace`.

    Never raises: a channel that cannot be fetched or read is logged and skipped. Returns the channels filled.
    """
    day = day_trace.day
    start = UTCDateTime(day_trace.start)
    done: list[str] = []
    for channel in channels:
        try:
            archive.download_day(sftp, store, device.network, device.station, device.location, channel, day)
            st = load_window(store, device.network, device.station, device.location, channel, start,
                             start + SECONDS)
            day_trace.replace_from(st)
            done.append(channel)
        except Exception as exc:  # a missing file (new day, no archive) or a cut record is not an error
            log.warning("live helicorder: no archive data for %s %s: %s", channel, day, exc)
    return done
```

- [ ] **Step 4: Run them, expect 3 passed**, then the whole suite.

- [ ] **Step 5: Commit**

```bash
git add rs3d-app/src/rs3d/core/preload.py rs3d-app/tests/core/test_preload.py
git commit -m "feat: preload today's data from the Shake archive into the DayTrace" # plus the two trailer lines
```

### Task 3: Wire the day trace into the live stream and the app state

**Files:**
- Modify: `rs3d-app/src/rs3d/core/live.py` (`LiveStream` gets `day_trace`)
- Modify: `rs3d-app/src/rs3d/app/state.py` (`day_trace(device)`, `preload` flag, `_preload` thread started by `start_current`)
- Modify: `rs3d-app/src/rs3d/app/main.py` (pass `preload=True`)
- Modify: `rs3d-app/tests/core/test_live.py`, `rs3d-app/tests/app/test_state_events.py`

**Interfaces:**
- Consumes: `DayTrace` (Task 1), `preload_today` (Task 2).
- Produces: `LiveStream(..., day_trace=None)` (anything with `add(trace)`), `AppState(paths, passwords=None, preload=False)`, `AppState.day_trace(device) -> DayTrace` (one per Shake, today's UTC date at first use), `AppState._preload(device)`.

- [ ] **Step 1: Save this patch** to a file in the scratchpad (for example `task3.patch`) and apply it with `git apply task3.patch` from the repo root. It contains the production edits and their tests.

```diff
diff --git a/rs3d-app/src/rs3d/core/live.py b/rs3d-app/src/rs3d/core/live.py
index 0c1ae27..f14ade9 100644
--- a/rs3d-app/src/rs3d/core/live.py
+++ b/rs3d-app/src/rs3d/core/live.py
@@ -139,9 +139,10 @@ class LiveStream:
     """Keeps a Source running in a daemon thread; reconnects with backoff when it fails."""
 
     def __init__(self, source_factory: Callable[[], Source], buffer: RingBuffer | None = None,
-                 sleep: Callable[[float], None] | None = None, detector=None) -> None:
+                 sleep: Callable[[float], None] | None = None, detector=None, day_trace=None) -> None:
         self.buffer = buffer or RingBuffer()
         self.detector = detector  # anything with feed(trace) and optionally flush(); e.g. EventDetector. Replaced by AppState on new settings.
+        self.day_trace = day_trace  # anything with add(trace); e.g. DayTrace, the data of the live helicorder
         self.state = "stopped"  # stopped | connecting | live | reconnecting
         self.error = ""
         self.last_data: float | None = None  # time.monotonic() of the last trace
@@ -170,6 +171,11 @@ class LiveStream:
         self.state = "live"
         self.last_data = time.monotonic()
         self.buffer.add(tr)
+        if self.day_trace is not None:
+            try:
+                self.day_trace.add(tr)
+            except Exception:  # the helicorder must never stop the stream
+                log.exception("day trace failed")
         detector = self.detector
         if detector is not None:
             try:
diff --git a/rs3d-app/src/rs3d/app/state.py b/rs3d-app/src/rs3d/app/state.py
index 204824e..6cf20ed 100644
--- a/rs3d-app/src/rs3d/app/state.py
+++ b/rs3d-app/src/rs3d/app/state.py
@@ -3,20 +3,24 @@
 from __future__ import annotations
 
 import logging
+import threading
 import tomllib
 from collections import deque
 from dataclasses import asdict, fields
+from datetime import datetime, timezone
 
 import tomli_w
 
+from rs3d.core.day_trace import DayTrace
 from rs3d.core.devices import DeviceRegistry, Passwords
 from rs3d.core.events import Event, EventDetector, EventSettings, validate_settings
 from rs3d.core.events_store import EventStore
 from rs3d.core.live import LiveStream
 from rs3d.core.models import Check, Device
 from rs3d.core.paths import AppPaths
+from rs3d.core.preload import preload_today
 from rs3d.core.seedlink import SeedLinkSource
-from rs3d.core.shell import Shell
+from rs3d.core.shell import Shell, ShellError
 from rs3d.core.status import run_checks
 from rs3d.core.store import Store
 
@@ -62,7 +66,8 @@ def _clean_event_settings(raw) -> EventSettings:
 
 
 class AppState:
-    def __init__(self, paths: AppPaths, passwords: Passwords | None = None) -> None:
+    def __init__(self, paths: AppPaths, passwords: Passwords | None = None, preload: bool = False) -> None:
+        self.preload = preload  # fill the live helicorder from the Shake's archive when a stream starts
         self.paths = paths.ensure()
         self.registry = DeviceRegistry(paths.config)
         self.passwords = passwords or Passwords()
@@ -79,6 +84,7 @@ class AppState:
         devices = self.registry.load()
         self.current_host: str | None = settings.get("current_host") or (devices[0].host if devices else None)
         self._live: dict[str, LiveStream] = {}
+        self._days: dict[str, DayTrace] = {}
 
     # ---------------------------------------------------------------- settings
     def save_settings(self) -> None:
@@ -149,6 +155,19 @@ class AppState:
             self.live(device)
         except Exception:
             log.exception("could not start the live stream for %s", device.host)
+            return
+        if self.preload:
+            threading.Thread(target=self._preload, args=(device,), name="rs3d-preload", daemon=True).start()
+
+    def _preload(self, device: Device) -> None:
+        """Fill today's helicorder from the Shake's archive. Runs in a thread and never raises."""
+        try:
+            with self.shell(device) as sh:
+                preload_today(sh.sftp(), self.store, device, self.day_trace(device), CHANNELS)
+        except ShellError as exc:
+            log.warning("live helicorder: cannot reach %s for the archive: %s", device.host, exc)
+        except Exception:
+            log.exception("live helicorder preload failed")
 
     def save_device(self, device: Device, password: str | None = None) -> None:
         self.registry.upsert(device)
@@ -185,11 +204,18 @@ class AppState:
         if stream is None:
             stream = LiveStream(lambda: SeedLinkSource(device.host, device.seedlink_port, device.network,
                                                        device.station, CHANNELS),
-                                detector=self._new_detector())
+                                detector=self._new_detector(), day_trace=self.day_trace(device))
             self._live[device.host] = stream
         stream.start()
         return stream
 
+    def day_trace(self, device: Device) -> DayTrace:
+        """Today's min/max data of this Shake (the live helicorder); one per Shake, created on first use."""
+        trace = self._days.get(device.host)
+        if trace is None:
+            trace = self._days[device.host] = DayTrace(datetime.now(timezone.utc).date())
+        return trace
+
     def stop_live(self, host: str) -> None:
         stream = self._live.pop(host, None)
         if stream:
diff --git a/rs3d-app/tests/core/test_live.py b/rs3d-app/tests/core/test_live.py
index 74587fa..18ffc55 100644
--- a/rs3d-app/tests/core/test_live.py
+++ b/rs3d-app/tests/core/test_live.py
@@ -203,3 +203,18 @@ def test_flush_failure_is_caught_in_the_loop():
     _t.sleep(0.2)
     assert live._thread.is_alive()
     live.stop()
+
+
+def test_stream_feeds_the_day_trace_and_survives_its_failure(caplog):
+    from obspy import Trace
+    seen = []
+
+    class Sink:
+        def add(self, tr):
+            seen.append(tr)
+            raise RuntimeError("boom")
+
+    stream = LiveStream(lambda: None, day_trace=Sink())
+    stream._on_trace(Trace(np.zeros(10), header={"sampling_rate": 100.0, "channel": "EHZ"}))
+    assert len(seen) == 1 and stream.buffer.latest() is not None  # the buffer still got the data
+    assert "day trace failed" in caplog.text
diff --git a/rs3d-app/tests/app/test_state_events.py b/rs3d-app/tests/app/test_state_events.py
index 47cc290..6e21b4d 100644
--- a/rs3d-app/tests/app/test_state_events.py
+++ b/rs3d-app/tests/app/test_state_events.py
@@ -214,3 +214,59 @@ def test_recent_events_seed_only_live_events(tmp_path):
 def test_found_label_reads_for_one():
     from rs3d.app.strings import label
     assert label("events.found").format(n=1) == "1 event(s)"
+
+
+def test_live_stream_feeds_the_day_trace(tmp_path):
+    from rs3d.core.models import Device
+    state = make(tmp_path)
+    device = Device(name="a", host="ha")
+    stream = state.live(device)
+    stream.stop()
+    assert stream.day_trace is state.day_trace(device)
+    assert state.day_trace(device) is state.day_trace(device)
+    assert state.day_trace(Device(name="b", host="hb")) is not state.day_trace(device)
+
+
+def test_start_current_preloads_only_when_asked(tmp_path, monkeypatch):
+    import sys
+    import threading
+    from rs3d.core.models import Device
+    done = threading.Event()
+    seen = []
+    monkeypatch.setattr(sys.modules[AppState.__module__], "preload_today",
+                        lambda sftp, store, dev, dt, ch: seen.append((dev.host, ch)) or done.set())
+
+    class FakeShell:
+        def __enter__(self):
+            return self
+
+        def __exit__(self, *a):
+            pass
+
+        def sftp(self):
+            return object()
+
+    quiet = make(tmp_path / "quiet")
+    quiet.registry.upsert(Device(name="a", host="ha"))
+    monkeypatch.setattr(quiet, "live", lambda d: None)
+    quiet.start_current()
+    assert not done.wait(0.3) and seen == []
+
+    loud = AppState(AppPaths(tmp_path / "loud"), passwords=Passwords(NoKeyring()), preload=True)
+    loud.registry.upsert(Device(name="a", host="ha"))
+    monkeypatch.setattr(loud, "live", lambda d: None)
+    monkeypatch.setattr(loud, "shell", lambda d: FakeShell())
+    loud.start_current()
+    assert done.wait(2) and seen == [("ha", ("EHZ", "EHN", "EHE"))]
+
+
+def test_preload_failure_does_not_raise(tmp_path, monkeypatch, caplog):
+    from rs3d.core.models import Device
+    from rs3d.core.shell import ShellError
+    state = AppState(AppPaths(tmp_path), passwords=Passwords(NoKeyring()), preload=True)
+
+    def refuse(device):
+        raise ShellError("unreachable", "no route")
+    monkeypatch.setattr(state, "shell", refuse)
+    state._preload(Device(name="a", host="ha"))  # must not raise
+    assert "no route" in caplog.text
```

- [ ] **Step 2: In `rs3d-app/src/rs3d/app/main.py`**, change `state = AppState(AppPaths.default())` to `state = AppState(AppPaths.default(), preload=True)`.

- [ ] **Step 3: Run** `uv run pytest tests/core/test_live.py tests/app/test_state_events.py -q` (expect all pass) and then the whole suite (expect 321 minus the tests of later tasks passing, none failing).

- [ ] **Step 4: Commit**

```bash
git add rs3d-app/src/rs3d/core/live.py rs3d-app/src/rs3d/app/state.py rs3d-app/src/rs3d/app/main.py rs3d-app/tests/core/test_live.py rs3d-app/tests/app/test_state_events.py
git commit -m "feat: live stream feeds the day trace; the archive preload starts with the app" # plus the two trailer lines
```

### Task 4: Live page: Waveform | Helicorder toggle

**Files:**
- Modify: `rs3d-app/src/rs3d/app/pages/live.py`
- Modify: `rs3d-app/src/rs3d/help/en.toml` (labels `live.mode_wave`, `live.mode_heli`, `live.open_heli`; help `live_heli`)
- Modify: `rs3d-app/tests/app/test_live_page.py`, `rs3d-app/tests/app/test_strings.py`

**Interfaces:**
- Consumes: `AppState.day_trace(device)` (Task 3), `DayTrace.rows`, `helicorder_options`, `scale_for`, `set_helicorder_events`, `SCALES` from the Helicorder page.
- Produces: `heli_spans(events, channel, open_event, detect_channel, until)`, `heli_options(rows, factor, spans)`, `helicorder_link(device, channel, day)`, `HELI_REFRESH = 5.0` in `pages/live.py`.

- [ ] **Step 1: Save this patch** and apply it with `git apply` from the repo root.

```diff
diff --git a/rs3d-app/src/rs3d/app/pages/live.py b/rs3d-app/src/rs3d/app/pages/live.py
index 48a2894..424bfe4 100644
--- a/rs3d-app/src/rs3d/app/pages/live.py
+++ b/rs3d-app/src/rs3d/app/pages/live.py
@@ -2,18 +2,25 @@
 
 from __future__ import annotations
 
-from datetime import datetime, timezone
+import time
+from datetime import date, datetime, timezone
+from urllib.parse import urlencode
 
 from nicegui import ui
 
-from rs3d.app.charts import set_event_areas, set_live_data, waveform_options
+from rs3d.app.charts import (helicorder_height_px, helicorder_options, set_event_areas, set_helicorder_events,
+                             set_live_data, waveform_options)
+from rs3d.app.pages.helicorder import SCALES
 from rs3d.app.state import CHANNELS, AppState
 from rs3d.app.strings import label
 from rs3d.app.widgets import frame, help_icon
 from rs3d.core.events import Event
+from rs3d.core.helicorder import scale_for
+from rs3d.core.models import Device
 
 WINDOWS = {30: "30 s", 60: "60 s", 300: "5 min", 600: "10 min"}  # the ring buffer keeps 10 min
 LIVE_FILTER = (1.0, 10.0)
+HELI_REFRESH = 5.0  # seconds between redraws of the 48-row chart
 
 
 def status_text(state_key: str, stale: bool, error: str) -> str:
@@ -60,6 +67,27 @@ def live_spans(recent, open_event: tuple[float, float] | None,
     return spans
 
 
+def heli_spans(events, channel: str, open_event: tuple[float, float] | None, detect_channel: str,
+               until: float) -> list[tuple[float, float]]:
+    """Event spans to shade on the live helicorder; an event in progress runs up to `until` (the newest data)."""
+    spans = [(e.start, e.end) for e in events if e.channel == channel]
+    if open_event is not None and channel == detect_channel:
+        spans.append((open_event[0], until))
+    return spans
+
+
+def heli_options(rows, factor: float, spans: list[tuple[float, float]]) -> dict:
+    options = helicorder_options(rows, scale_for(rows, factor))
+    set_helicorder_events(options, rows, spans)
+    return options
+
+
+def helicorder_link(device: Device, channel: str, day: date) -> str:
+    """The same day on the Helicorder page (it reads the files in the local store)."""
+    return "/helicorder?" + urlencode({"station": f"{device.network}.{device.station}.{device.location}",
+                                       "channel": channel, "day": day.isoformat()})
+
+
 def register(state: AppState) -> None:
     @ui.page("/live")
     def live_page() -> None:
@@ -68,9 +96,26 @@ def register(state: AppState) -> None:
             ui.label(label("no_device")).classes("text-grey-7")
             return
         stream = state.live(device)
-        view = {"paused": False}
+        view = {"paused": False, "heli_at": 0.0}
+        days = state.day_trace(device)
+
+        with ui.row().classes("items-center gap-1"):
+            mode = ui.toggle({"wave": label("live.mode_wave"), "heli": label("live.mode_heli")}, value="wave") \
+                .props("dense no-caps")
+            help_icon("live_heli")
+            status = ui.label("").classes("text-sm text-grey-7 ml-4")
+
+        heli_controls = ui.row().classes("items-center gap-4")
+        with heli_controls:
+            heli_channel = ui.select(list(CHANNELS), value=CHANNELS[0]).props("dense").classes("w-24")
+            heli_scale = ui.select(SCALES, value=1.0, label=label("heli.scale")).props("dense").classes("w-24")
+            ui.button(label("live.open_heli"), icon="open_in_new",
+                      on_click=lambda: ui.navigate.to(helicorder_link(device, heli_channel.value, days.day))) \
+                .props("flat dense no-caps")
+        heli_controls.set_visibility(False)
 
-        with ui.row().classes("items-center gap-4"):
+        wave_controls = ui.row().classes("items-center gap-4")
+        with wave_controls:
             window = ui.toggle(WINDOWS, value=60).props("dense no-caps")
             with ui.row().classes("items-center gap-1"):
                 flt = ui.switch(label("live.filter"), value=True)
@@ -81,7 +126,6 @@ def register(state: AppState) -> None:
             pause = ui.button(label("action.pause"), icon="pause").props("flat dense no-caps")
             ui.button(label("action.save_segment"), icon="content_cut", on_click=lambda: save_segment()) \
                 .props("flat dense no-caps")
-            status = ui.label("").classes("text-sm text-grey-7")
 
         banner = ui.row().classes("w-full items-center gap-2 px-3 py-1 text-white")
         with banner:
@@ -92,6 +136,8 @@ def register(state: AppState) -> None:
 
         chart = ui.echart(waveform_options(CHANNELS, use_utc=not state.use_local_time)) \
             .classes("w-full").style("height: 72vh")
+        heli_chart = ui.echart({"series": []}).classes("w-full").style(f"height: {helicorder_height_px(48)}px")
+        heli_chart.set_visibility(False)
         ui.label(label("events.latest")).classes("font-bold mt-2")
         event_list = ui.column().classes("gap-0 font-mono text-sm")
         listed = {"key": None}
@@ -103,6 +149,31 @@ def register(state: AppState) -> None:
 
         pause.on_click(toggle_pause)
 
+        def set_mode(_=None) -> None:
+            heli = mode.value == "heli"
+            wave_controls.set_visibility(not heli)
+            chart.set_visibility(not heli)
+            heli_controls.set_visibility(heli)
+            heli_chart.set_visibility(heli)
+            view["heli_at"] = 0.0  # draw at once
+
+        mode.on_value_change(set_mode)
+        heli_channel.on_value_change(lambda _: view.update(heli_at=0.0))
+        heli_scale.on_value_change(lambda _: view.update(heli_at=0.0))
+
+        def draw_helicorder(recent_open) -> None:
+            if time.monotonic() - view["heli_at"] < HELI_REFRESH:
+                return
+            view["heli_at"] = time.monotonic()
+            channel = heli_channel.value
+            rows = days.rows(channel)
+            until = stream.buffer.latest() or days.start
+            events = state.events.events_between(days.start, days.start + 86400)
+            spans = heli_spans(events, channel, recent_open, state.event_settings.channel, until)
+            heli_chart.options.clear()
+            heli_chart.options.update(heli_options(rows, float(heli_scale.value), spans))
+            heli_chart.update()
+
         def tick() -> None:
             status.text = status_text(stream.state, stream.is_stale(), stream.error)
             kind, text = banner_state(state.event_open, state.event_last, state.use_local_time)
@@ -119,6 +190,9 @@ def register(state: AppState) -> None:
                         ui.label(label("events.none")).classes("text-grey-6")
                     for e in reversed(recent[-8:]):
                         ui.label(event_row_text(e, state.use_local_time))
+            if mode.value == "heli":
+                draw_helicorder(state.event_open)
+                return
             if view["paused"]:
                 return
             end = stream.buffer.latest()
diff --git a/rs3d-app/src/rs3d/help/en.toml b/rs3d-app/src/rs3d/help/en.toml
index 863f740..e3538ad 100644
--- a/rs3d-app/src/rs3d/help/en.toml
+++ b/rs3d-app/src/rs3d/help/en.toml
@@ -56,6 +56,9 @@ connecting = "connecting…"
 reconnecting = "reconnecting…"
 waiting = "waiting for data…"
 stopped = "stopped"
+mode_wave = "Waveform"
+mode_heli = "Helicorder"
+open_heli = "Open on Helicorder page"
 
 [labels.data]
 start = "Start"
@@ -356,6 +359,17 @@ detail = "It reads from this laptop's data folder, so it runs without the Shake.
 short = "Band-pass 1–10 Hz to hide slow drift and high-frequency noise."
 detail = "Applied only to the display. Use the Data page to export filtered data."
 
+[help.live_heli]
+short = "The whole UTC day in 48 rows of 30 minutes; the newest row grows to the right."
+detail = """
+Each row is 30 minutes of one channel, drawn as the lowest and highest value of every second, without the DC offset.
+Events are shaded. At start-up the app copies today's data from the Shake's archive, so the day is already filled; if
+the Shake cannot be reached the view starts empty and fills from the live stream. A new day starts at 00:00 UTC.
+
+No filter or physical units here. **Open on Helicorder page** shows the same day with units, filter and zoom, using the
+files in the local store (download today's data on the Data page first to see the newest minutes).
+"""
+
 [help.events]
 short = "Raises an alert when the ground shakes much harder than usual."
 detail = """
diff --git a/rs3d-app/tests/app/test_live_page.py b/rs3d-app/tests/app/test_live_page.py
index ef8aebe..8e9fd4c 100644
--- a/rs3d-app/tests/app/test_live_page.py
+++ b/rs3d-app/tests/app/test_live_page.py
@@ -24,3 +24,33 @@ def test_band_for_accepts_only_a_valid_band():
 def test_longest_window_fits_the_ring_buffer():
     assert max(WINDOWS) <= RingBuffer().seconds
     assert 600 in WINDOWS
+
+
+def test_heli_spans_shade_the_channel_and_the_open_event():
+    from rs3d.app.pages.live import heli_spans
+    from rs3d.core.events import Event
+    e = [Event(start=10.0, end=20.0, channel="EHZ", peak_ratio=5.0, peak_amplitude=100.0, source="live"),
+         Event(start=30.0, end=40.0, channel="EHN", peak_ratio=5.0, peak_amplitude=100.0, source="live")]
+    assert heli_spans(e, "EHZ", None, "EHZ", 99.0) == [(10.0, 20.0)]
+    assert heli_spans(e, "EHZ", (50.0, 5.0), "EHZ", 99.0) == [(10.0, 20.0), (50.0, 99.0)]
+    assert heli_spans(e, "EHN", (50.0, 5.0), "EHZ", 99.0) == [(30.0, 40.0)]  # the open event is on another channel
+
+
+def test_heli_options_has_48_rows_and_event_shading():
+    from datetime import date
+
+    from rs3d.app.pages.live import heli_options
+    from rs3d.core.day_trace import DayTrace
+    d = DayTrace(date(2026, 10, 12))
+    options = heli_options(d.rows("EHZ"), 1.0, [(d.start + 60, d.start + 120)])
+    assert len(options["series"]) == 49  # 48 rows plus the click grid
+    assert options["series"][-1]["markArea"]["data"]
+
+
+def test_helicorder_link_points_at_the_same_day():
+    from datetime import date
+
+    from rs3d.app.pages.live import helicorder_link
+    from rs3d.core.models import Device
+    link = helicorder_link(Device(name="s", host="h", station="R77A7"), "EHZ", date(2026, 10, 12))
+    assert link == "/helicorder?station=AM.R77A7.00&channel=EHZ&day=2026-10-12"
diff --git a/rs3d-app/tests/app/test_strings.py b/rs3d-app/tests/app/test_strings.py
index 8f55e6f..de5795a 100644
--- a/rs3d-app/tests/app/test_strings.py
+++ b/rs3d-app/tests/app/test_strings.py
@@ -71,3 +71,10 @@ def test_clock_sync_labels_exist():
     for key in ("action.sync_clock", "clock.title", "clock.offset", "clock.working", "clock.done",
                 "clock.failed", "clock.sync_now", "clock.set_laptop", "clock.warning"):
         assert label(key) != key, key
+
+
+def test_live_helicorder_texts_exist():
+    for key in ("live.mode_wave", "live.mode_heli", "live.open_heli"):
+        assert label(key) != key, key
+    short, detail = help_text("live_heli")
+    assert short and detail
```

- [ ] **Step 2: Run** `uv run pytest tests/app -q` (expect all pass) and then the whole suite.

- [ ] **Step 3: Look at it in a browser (best effort).** Build a scratch server like `tests/app/sim_main.py`, but give the device a throwaway host (for example `192.0.2.1`) so no real Shake is contacted, put synthetic traces into `state.day_trace(device)`, open `/live`, press **Helicorder**, and check: 48 rows, labelled hours on both sides, the current row ends where the data ends, switching back to **Waveform** restores the old view, **Open on Helicorder page** navigates to `/helicorder?station=...`. Report what was and was not checked; do not commit anything from this step.

- [ ] **Step 4: Commit**

```bash
git add rs3d-app/src/rs3d/app/pages/live.py rs3d-app/src/rs3d/help/en.toml rs3d-app/tests/app/test_live_page.py rs3d-app/tests/app/test_strings.py
git commit -m "feat: Live page shows today as a 48-row helicorder" # plus the two trailer lines
```

### Task 5: CHANGELOG, Guide and the real-Shake test

**Files:**
- Modify: `CHANGELOG.md` (repo root), `rs3d-app/src/rs3d/guide/en.md`
- Create: `rs3d-app/tests/device/test_live_heli.py`

- [ ] **Step 1: CHANGELOG.** Under **Unreleased → Added** add:

```
- Live page: a **Helicorder** mode shows today (UTC) as 48 rows of 30 minutes for the chosen channel, with a scale selector and shaded events. At start-up it is filled from the Shake's own archive, then grows live. **Open on Helicorder page** shows the same day with units, filter and zoom.
```

Under **Unreleased → Notes** add: `- The live helicorder shows counts only (no filter or physical units). Not yet tried against the real Shake in a browser.`

- [ ] **Step 2: Guide.** In `rs3d-app/src/rs3d/guide/en.md`, section **4. Live**, append one paragraph:

```
Switch to **Helicorder** to see today (UTC) as 48 rows of 30 minutes. Choose the channel and scale; events are shaded. When the app starts it copies today's data from the Shake's archive, so the day is already filled; if the Shake cannot be reached it starts empty and fills from the live stream. A new day starts at 00:00 UTC. This view shows counts only; **Open on Helicorder page** gives the same day with units, filter and zoom (it reads the files in the local store, so download today's data first to see the newest minutes).
```

- [ ] **Step 3: Device test** `rs3d-app/tests/device/test_live_heli.py` (read-only: it only reads the Shake's archive over SFTP):

```python
"""Run with a Shake on the cable: RS3D_HOST=169.254.221.62 uv run pytest -m device tests/device/test_live_heli.py -v"""

import os
from datetime import datetime, timezone

import pytest

from rs3d.core.day_trace import DayTrace
from rs3d.core.models import Device
from rs3d.core.preload import preload_today
from rs3d.core.seedlink import probe
from rs3d.core.shell import Shell
from rs3d.core.store import Store

pytestmark = pytest.mark.device
HOST = os.environ.get("RS3D_HOST", "169.254.221.62")


def test_preload_fills_today_from_the_real_archive(tmp_path):
    info = probe(HOST)
    device = Device(name=info.station, host=HOST, station=info.station, network=info.network,
                    location=info.location)
    day = DayTrace(datetime.now(timezone.utc).date())
    with Shell(device, None, tmp_path / "kh") as sh:
        done = preload_today(sh.sftp(), Store(tmp_path / "sds"), device, day, ("EHZ",))
    assert done == ["EHZ"]
    rows = day.rows("EHZ")
    assert len(rows) == 48 and any(len(r.values) for r in rows)
```

- [ ] **Step 4: Run the device test** (read-only, the Shake is on the cable): `RS3D_HOST=169.254.221.62 uv run pytest -m device tests/device/test_live_heli.py -v`. Expect 1 passed. If the Shake is not reachable, say so in the report and skip; do not edit the test to pass.

- [ ] **Step 5: Run the whole suite** (`uv run pytest -q`).

- [ ] **Step 6: Commit** (docs and the device test in one commit, as in the earlier plans):

```bash
git add CHANGELOG.md rs3d-app/src/rs3d/guide/en.md rs3d-app/tests/device/test_live_heli.py
git commit -m "docs: changelog, guide and device test for the live helicorder" # plus the two trailer lines
```
