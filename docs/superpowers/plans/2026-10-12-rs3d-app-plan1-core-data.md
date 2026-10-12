# RS3D App – Plan 1: Core Data Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the UI-independent data layer of the RS3D app: a local SDS store of miniSEED day files, coverage computation (downloaded / on Shake / gap), processing and export (miniSEED, CSV, PNG, PDF) and generation of equivalent ObsPy code.

**Architecture:** A new Python package `rs3d-app` in the subdirectory `rs3d-app/` of the repository, with `src/rs3d/core/` holding plain modules that never import UI code. All modules work on a local SDS directory tree, so every test runs on synthetic data without a Raspberry Shake. Spec: `docs/superpowers/specs/2026-10-12-rs3d-app-design.md` (sections 4, 5.4, 6, 7, 8).

**Tech Stack:** Python ≥ 3.11, uv, hatchling, ObsPy 1.5.1, NumPy, Matplotlib (Agg backend), pytest.

**This is plan 1 of 3.** Plan 2 (device connectivity: SSH, status checks, live SeedLink, archive sync, response, Set IP) and Plan 3 (NiceGUI user interface) build on the interfaces defined here.

---

## Context for the engineer

- A Raspberry Shake 3D records ground velocity on three channels `EHZ`, `EHN`, `EHE` at 100 samples/s. Data is identified by **network.station.location.channel**; our device is `AM.R77A7.00.EH?`.
- **miniSEED** is the standard binary format for seismic time series. **SDS** (SeisComP Data Structure) is a directory layout with one file per channel per day:
  `<root>/<YEAR>/<NET>/<STA>/<CHA>.D/<NET>.<STA>.<LOC>.<CHA>.D.<YEAR>.<DOY>` where DOY is the 3-digit day of year. ObsPy reads it with `obspy.clients.filesystem.sds.Client`.
- **Gaps:** when data is missing, ObsPy returns several `Trace` objects for one channel. We never fill gaps with invented values.
- **Response:** converting raw `counts` to velocity in m/s needs the instrument response (an ObsPy `Inventory`). Where it comes from is Plan 2; here it is a parameter.
- `obspy.UTCDateTime` is **not hashable**: never put it in a `set` or use it as a dict key. Use `.ns` (int nanoseconds) when you need a key.
- All times are UTC.

## File structure

```
rs3d-app/
├── pyproject.toml            # package metadata, deps, pytest config
├── README.md
├── src/rs3d/
│   ├── __init__.py           # version
│   └── core/
│       ├── __init__.py
│       ├── models.py         # Level, Device, Check, Selection
│       ├── store.py          # Store: SDS paths, days on disk, load(Selection)
│       ├── coverage.py       # State, Segment, local_spans(), coverage()
│       ├── export.py         # process(), load_processed(), write_mseed/csv/plot()
│       └── codegen.py        # generate(): ObsPy code equal to load_processed()
└── tests/
    ├── __init__.py
    ├── conftest.py           # synthetic SDS store + test inventory fixtures
    └── core/
        ├── __init__.py
        ├── test_models.py
        ├── test_store.py
        ├── test_coverage.py
        ├── test_export.py
        └── test_codegen.py
```

All commands below run from `rs3d-app/` unless stated otherwise.

---

### Task 1: Package scaffold

**Files:**
- Create: `rs3d-app/pyproject.toml`
- Create: `rs3d-app/README.md`
- Create: `rs3d-app/src/rs3d/__init__.py`
- Create: `rs3d-app/src/rs3d/core/__init__.py`
- Create: `rs3d-app/tests/__init__.py` (empty)
- Create: `rs3d-app/tests/core/__init__.py` (empty)

- [ ] **Step 1: Create `rs3d-app/pyproject.toml`**

```toml
[project]
name = "rs3d-app"
version = "0.1.0"
description = "Status, live view and data export for Raspberry Shake 3D over Ethernet"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "obspy>=1.5.1",
    "matplotlib>=3.8",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/rs3d"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["device: needs a Raspberry Shake connected over Ethernet"]
addopts = "-m 'not device'"
```

- [ ] **Step 2: Create `rs3d-app/README.md`**

```markdown
# rs3d-app

Status, live view and data export for Raspberry Shake 3D over Ethernet.

```bash
uv sync
uv run pytest
```
```

- [ ] **Step 3: Create the package files**

`rs3d-app/src/rs3d/__init__.py`:

```python
"""RS3D app: status, live view and data export for Raspberry Shake 3D."""

__version__ = "0.1.0"
```

`rs3d-app/src/rs3d/core/__init__.py`:

```python
"""UI-independent logic."""
```

Create the empty files `rs3d-app/tests/__init__.py` and `rs3d-app/tests/core/__init__.py`.

Append to the repository root `.gitignore` (the existing `.venv` and `__pycache__/` entries already cover the rest):

```
# pytest
.pytest_cache/
```

- [ ] **Step 4: Install and check the environment**

Run: `cd rs3d-app && uv sync && uv run python -c "import rs3d, obspy; print(rs3d.__version__, obspy.__version__)"`
Expected: `0.1.0 1.5.1` (ObsPy may be newer).

Run: `uv run pytest -q`
Expected: `no tests ran` (exit code 5 is fine at this point).

- [ ] **Step 5: Commit**

```bash
git add .gitignore rs3d-app/pyproject.toml rs3d-app/README.md rs3d-app/uv.lock rs3d-app/src rs3d-app/tests
git commit -m "feat(rs3d-app): package scaffold"
```

---

### Task 2: Data models

**Files:**
- Create: `rs3d-app/src/rs3d/core/models.py`
- Test: `rs3d-app/tests/core/test_models.py`

- [ ] **Step 1: Write the failing tests** – `rs3d-app/tests/core/test_models.py`:

```python
import pytest
from obspy import UTCDateTime

from rs3d.core.models import Check, Device, Level, Selection

T0 = UTCDateTime("2026-10-12T00:00:00")


def test_selection_defaults():
    sel = Selection("AM", "R77A7", "00", T0, T0 + 60)
    assert sel.channels == ("EHZ", "EHN", "EHE")
    assert sel.units == "counts"
    assert sel.filter is None


@pytest.mark.parametrize("kwargs, message", [
    ({"end": T0}, "end must be after start"),
    ({"channels": ()}, "at least one channel"),
    ({"units": "g"}, "units must be one of"),
    ({"filter": (10.0, 1.0)}, "0 < fmin < fmax"),
    ({"filter": (0.0, 1.0)}, "0 < fmin < fmax"),
])
def test_selection_rejects_bad_input(kwargs, message):
    args = {"network": "AM", "station": "R77A7", "location": "00", "start": T0, "end": T0 + 60}
    args.update(kwargs)
    with pytest.raises(ValueError, match=message):
        Selection(**args)


def test_device_defaults():
    d = Device(name="R77A7", host="169.254.221.62")
    assert (d.seedlink_port, d.ssh_user, d.network, d.location) == (18000, "myshake", "AM", "00")


def test_check_level_values():
    c = Check(id="ssh", level=Level.ERROR, help_id="ssh.auth")
    assert c.level.value == "error"
    assert c.action is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rs3d.core.models'`

- [ ] **Step 3: Implement** – `rs3d-app/src/rs3d/core/models.py`:

```python
"""Plain data types shared by the core modules and the UI."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from obspy import UTCDateTime

UNITS = ("counts", "m/s")


class Level(str, Enum):
    OK = "ok"
    WARN = "warn"
    ERROR = "error"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class Device:
    """A Shake the app can talk to. The SSH password lives in the keyring, not here."""

    name: str
    host: str
    seedlink_port: int = 18000
    ssh_user: str = "myshake"
    key_path: Path | None = None
    network: str = "AM"
    station: str = ""
    location: str = "00"


@dataclass(frozen=True)
class Check:
    """One row of the Status page. Wording comes from help/en.yaml via help_id."""

    id: str
    level: Level
    value: str = ""
    help_id: str = ""
    action: str | None = None


@dataclass(frozen=True)
class Selection:
    """What the user picked on the Data page. Export and codegen both consume it."""

    network: str
    station: str
    location: str
    start: UTCDateTime
    end: UTCDateTime
    channels: tuple[str, ...] = ("EHZ", "EHN", "EHE")
    filter: tuple[float, float] | None = None
    units: str = "counts"

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if not self.channels:
            raise ValueError("select at least one channel")
        if self.units not in UNITS:
            raise ValueError(f"units must be one of {UNITS}")
        if self.filter is not None:
            fmin, fmax = self.filter
            if not 0 < fmin < fmax:
                raise ValueError("filter must satisfy 0 < fmin < fmax")
```

Note: the dataclasses are `frozen=True` for immutability, but `Selection` holds `UTCDateTime` values, which are not hashable, so never put a `Selection` in a set or use it as a dict key.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/core/test_models.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add rs3d-app/src/rs3d/core/models.py rs3d-app/tests/core/test_models.py
git commit -m "feat(rs3d-app): core data models"
```

---

### Task 3: Synthetic test data and the local SDS store

**Files:**
- Create: `rs3d-app/tests/conftest.py`
- Create: `rs3d-app/src/rs3d/core/store.py`
- Test: `rs3d-app/tests/core/test_store.py`

The fixture store contains AM.R77A7.00 EHZ/EHN/EHE at 100 Hz from 2026-10-11T23:55 to 2026-10-12T00:10 (crossing midnight, so two day files per channel) with a gap from 00:02 to 00:03 on all channels. The `inventory` fixture is a simple geophone-like response used to test the m/s path.

- [ ] **Step 1: Create the fixtures** – `rs3d-app/tests/conftest.py`:

```python
"""Synthetic Raspberry Shake data, so core tests never need a device.

Layout of the fixture store (all three channels, 100 Hz, AM.R77A7.00):
  2026-10-11T23:55:00 -> 2026-10-12T00:02:00   data   (crosses midnight)
  2026-10-12T00:02:00 -> 2026-10-12T00:03:00   gap
  2026-10-12T00:03:00 -> 2026-10-12T00:10:00   data
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest
from obspy import Inventory, Stream, Trace, UTCDateTime
from obspy.core.inventory import Channel, Network, Site, Station
from obspy.core.inventory.response import Response

from rs3d.core.store import Store

NET, STA, LOC = "AM", "R77A7", "00"
CHANNELS = ("EHZ", "EHN", "EHE")
RATE = 100.0
T_START = UTCDateTime("2026-10-11T23:55:00")
GAP_START = UTCDateTime("2026-10-12T00:02:00")
GAP_END = UTCDateTime("2026-10-12T00:03:00")
T_END = UTCDateTime("2026-10-12T00:10:00")
DAY1, DAY2 = date(2026, 10, 11), date(2026, 10, 12)


def _trace(channel: str, start: UTCDateTime, end: UTCDateTime, seed: int) -> Trace:
    n = int(round((end - start) * RATE))
    rng = np.random.default_rng(seed)
    data = rng.integers(-5000, 5000, n).astype(np.int32)
    return Trace(data=data, header={
        "network": NET, "station": STA, "location": LOC, "channel": channel,
        "starttime": start, "sampling_rate": RATE,
    })


@pytest.fixture
def store(tmp_path) -> Store:
    s = Store(tmp_path / "sds")
    midnight = UTCDateTime("2026-10-12T00:00:00")
    for i, channel in enumerate(CHANNELS):
        pieces = [
            _trace(channel, T_START, GAP_START, seed=10 + i),
            _trace(channel, GAP_END, T_END, seed=20 + i),
        ]
        whole = Stream(pieces)
        for day, a, b in ((DAY1, T_START, midnight), (DAY2, midnight, T_END)):
            part = whole.slice(a, b - 1 / RATE)
            path = s.day_path(NET, STA, LOC, channel, day)
            path.parent.mkdir(parents=True, exist_ok=True)
            part.write(str(path), format="MSEED")
    return s


@pytest.fixture
def inventory() -> Inventory:
    """A simple 4.5 Hz geophone-like response, good enough to test the m/s path."""
    resp = Response.from_paz(
        zeros=[0j, 0j], poles=[-19.78 + 20.20j, -19.78 - 20.20j],
        stage_gain=3.99e8, stage_gain_frequency=5.0,
        input_units="M/S", output_units="COUNTS", normalization_frequency=5.0,
    )
    channels = [
        Channel(code=c, location_code=LOC, latitude=0, longitude=0, elevation=0, depth=0,
                sample_rate=RATE, response=resp, start_date=UTCDateTime(2020, 1, 1))
        for c in CHANNELS
    ]
    station = Station(code=STA, latitude=0, longitude=0, elevation=0, channels=channels,
                      site=Site(name="test"), start_date=UTCDateTime(2020, 1, 1))
    return Inventory(networks=[Network(code=NET, stations=[station])], source="rs3d-tests")
```

- [ ] **Step 2: Write the failing tests** – `rs3d-app/tests/core/test_store.py`:

```python
from datetime import date

from obspy import UTCDateTime

from rs3d.core.models import Selection
from rs3d.core.store import Store
from tests.conftest import DAY1, DAY2, GAP_END, GAP_START, T_START


def test_day_path_is_sds_layout(tmp_path):
    s = Store(tmp_path)
    p = s.day_path("AM", "R77A7", "00", "EHZ", date(2026, 10, 12))
    assert p == tmp_path / "2026" / "AM" / "R77A7" / "EHZ.D" / "AM.R77A7.00.EHZ.D.2026.285"


def test_days_lists_files(store):
    assert store.days("AM", "R77A7", "00", "EHZ") == {DAY1, DAY2}
    assert store.days("AM", "R77A7", "00", "XXX") == set()


def test_load_trims_to_selection_across_midnight(store):
    sel = Selection("AM", "R77A7", "00", T_START + 60, UTCDateTime("2026-10-12T00:01:00"))
    st = store.load(sel)
    assert sorted(tr.stats.channel for tr in st) == ["EHE", "EHN", "EHZ"]
    for tr in st:
        assert tr.stats.starttime == sel.start
        assert abs(tr.stats.endtime - sel.end) <= tr.stats.delta


def test_load_keeps_gap_as_separate_traces(store):
    sel = Selection("AM", "R77A7", "00", GAP_START - 30, GAP_END + 30, channels=("EHZ",))
    st = store.load(sel)
    assert len(st) == 2
    first, second = sorted(st, key=lambda tr: tr.stats.starttime)
    assert first.stats.endtime < GAP_START
    assert second.stats.starttime == GAP_END
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rs3d.core.store'` (raised while importing `tests/conftest.py`).

- [ ] **Step 4: Implement** – `rs3d-app/src/rs3d/core/store.py`:

```python
"""Local SDS (SeisComP Data Structure) store of miniSEED day files."""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from obspy import Stream
from obspy.clients.filesystem.sds import Client

from rs3d.core.models import Selection

_DAY_FILE = re.compile(r"^(?P<net>[^.]+)\.(?P<sta>[^.]+)\.(?P<loc>[^.]*)\.(?P<cha>[^.]+)\.D\.(?P<year>\d{4})\.(?P<doy>\d{3})$")


class Store:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def day_path(self, network: str, station: str, location: str, channel: str, day: date) -> Path:
        doy = day.timetuple().tm_yday
        name = f"{network}.{station}.{location}.{channel}.D.{day.year}.{doy:03d}"
        return self.root / str(day.year) / network / station / f"{channel}.D" / name

    def days(self, network: str, station: str, location: str, channel: str) -> set[date]:
        """Days that have a file in the store for this channel."""
        found: set[date] = set()
        for path in self.root.glob(f"*/{network}/{station}/{channel}.D/*"):
            m = _DAY_FILE.match(path.name)
            if m and m["loc"] == location:
                found.add(date(int(m["year"]), 1, 1) + timedelta(days=int(m["doy"]) - 1))
        return found

    def load(self, sel: Selection) -> Stream:
        """Raw counts for the selection, trimmed to [start, end]. Gaps stay as separate traces."""
        client = Client(str(self.root))
        st = Stream()
        for channel in sel.channels:
            st += client.get_waveforms(sel.network, sel.station, sel.location, channel, sel.start, sel.end)
        st.trim(sel.start, sel.end)
        return st
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/core/test_store.py tests/core/test_models.py -v`
Expected: 12 passed

- [ ] **Step 6: Commit**

```bash
git add rs3d-app/tests/conftest.py rs3d-app/src/rs3d/core/store.py rs3d-app/tests/core/test_store.py
git commit -m "feat(rs3d-app): local SDS store with synthetic test data"
```

---

### Task 4: Coverage (downloaded / on Shake / gap)

**Files:**
- Create: `rs3d-app/src/rs3d/core/coverage.py`
- Test: `rs3d-app/tests/core/test_coverage.py`

Rules (spec 5.4 and 6): time with local data is `LOCAL`. Time without local data is `REMOTE` when its day exists on the Shake and is either not downloaded yet or is the newest remote day (today's file keeps growing). Everything else is `GAP`. Local traces separated by at most half a sample are merged.

- [ ] **Step 1: Write the failing tests** – `rs3d-app/tests/core/test_coverage.py`:

```python
from datetime import date

import pytest
from obspy import UTCDateTime

from rs3d.core.coverage import State, coverage, local_spans
from tests.conftest import DAY1, DAY2, GAP_END, GAP_START, T_END, T_START

NSLC = ("AM", "R77A7", "00", "EHZ")


def states(segments):
    return [(str(s.start), str(s.end), s.state) for s in segments]


def test_local_spans_merge_across_midnight_and_keep_gap(store):
    spans = local_spans(store, *NSLC, T_START - 60, T_END + 60)
    assert spans == [(T_START, GAP_START), (GAP_END, T_END)]


def test_coverage_with_everything_downloaded(store):
    segs = coverage(store, *NSLC, T_START, T_END, remote_days={DAY1, DAY2})
    # DAY2 is the newest remote day: time without local data there is REMOTE (file still growing)
    assert states(segs) == [
        (str(T_START), str(GAP_START), State.LOCAL),
        (str(GAP_START), str(GAP_END), State.REMOTE),
        (str(GAP_END), str(T_END), State.LOCAL),
    ]


def test_gap_in_a_finished_day_is_gap(store):
    day3 = date(2026, 10, 13)
    segs = coverage(store, *NSLC, T_START, T_END, remote_days={DAY1, DAY2, day3})
    assert [s.state for s in segs] == [State.LOCAL, State.GAP, State.LOCAL]


def test_days_only_on_shake_are_remote(store):
    start, end = UTCDateTime("2026-10-13T00:00:00"), UTCDateTime("2026-10-14T00:00:00")
    segs = coverage(store, *NSLC, start, end, remote_days={DAY1, DAY2, date(2026, 10, 13)})
    assert states(segs) == [(str(start), str(end), State.REMOTE)]


def test_nothing_anywhere_is_gap(store):
    start, end = UTCDateTime("2026-10-01T00:00:00"), UTCDateTime("2026-10-01T06:00:00")
    segs = coverage(store, *NSLC, start, end, remote_days=set())
    assert states(segs) == [(str(start), str(end), State.GAP)]


def test_rejects_empty_range(store):
    with pytest.raises(ValueError):
        coverage(store, *NSLC, T_END, T_START, remote_days=set())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_coverage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rs3d.core.coverage'`

- [ ] **Step 3: Implement** – `rs3d-app/src/rs3d/core/coverage.py`:

```python
"""Which parts of a time range are downloaded, only on the Shake, or missing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum

from obspy import UTCDateTime, read

from rs3d.core.store import Store


class State(str, Enum):
    LOCAL = "local"    # downloaded to the laptop
    REMOTE = "remote"  # on the Shake, not downloaded yet
    GAP = "gap"        # no data anywhere


@dataclass(frozen=True)
class Segment:
    start: UTCDateTime
    end: UTCDateTime
    state: State


def _day_start(day: date) -> UTCDateTime:
    return UTCDateTime(day.year, day.month, day.day)


def _days_between(start: UTCDateTime, end: UTCDateTime) -> list[date]:
    first, last = start.date, (end - 1e-6).date
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def local_spans(
    store: Store, network: str, station: str, location: str, channel: str,
    start: UTCDateTime, end: UTCDateTime,
) -> list[tuple[UTCDateTime, UTCDateTime]]:
    """Time spans with local data, clipped to [start, end] and merged.

    Two traces are joined when the hole between them is at most 1.5 samples.
    """
    spans: list[tuple[UTCDateTime, UTCDateTime, float]] = []
    for day in _days_between(start, end):
        path = store.day_path(network, station, location, channel, day)
        if not path.exists():
            continue
        for tr in read(str(path), headonly=True):
            delta = tr.stats.delta
            s, e = tr.stats.starttime, tr.stats.endtime + delta
            if e > start and s < end:
                spans.append((max(s, start), min(e, end), delta))
    spans.sort(key=lambda x: x[0])
    merged: list[tuple[UTCDateTime, UTCDateTime]] = []
    for s, e, delta in spans:
        if merged and s - merged[-1][1] <= 0.5 * delta:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def coverage(
    store: Store, network: str, station: str, location: str, channel: str,
    start: UTCDateTime, end: UTCDateTime, remote_days: set[date],
) -> list[Segment]:
    """Split [start, end] into LOCAL / REMOTE / GAP segments for one channel.

    Time without local data counts as REMOTE when its day exists on the Shake and is
    either not downloaded yet or is the newest remote day (the file still growing).
    """
    if end <= start:
        raise ValueError("end must be after start")
    spans = local_spans(store, network, station, location, channel, start, end)
    local_days = store.days(network, station, location, channel)
    newest_remote = max(remote_days) if remote_days else None

    cuts = [start, end]  # UTCDateTime is not hashable: dedupe by nanoseconds
    for day in _days_between(start, end):
        for t in (_day_start(day), _day_start(day + timedelta(days=1))):
            if start < t < end:
                cuts.append(t)
    for s, e in spans:
        cuts += [s, e]
    points = sorted({t.ns: t for t in cuts}.values())

    segments: list[Segment] = []
    for a, b in zip(points, points[1:]):
        if b <= a:
            continue
        mid = a + (b - a) / 2
        if any(s <= mid < e for s, e in spans):
            state = State.LOCAL
        else:
            day = mid.date
            if day in remote_days and (day not in local_days or day == newest_remote):
                state = State.REMOTE
            else:
                state = State.GAP
        if segments and segments[-1].state == state and segments[-1].end == a:
            segments[-1] = Segment(segments[-1].start, b, state)
        else:
            segments.append(Segment(a, b, state))
    return segments
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/core/test_coverage.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add rs3d-app/src/rs3d/core/coverage.py rs3d-app/tests/core/test_coverage.py
git commit -m "feat(rs3d-app): coverage segments for the data bar"
```

---

### Task 5: Processing and export

**Files:**
- Create: `rs3d-app/src/rs3d/core/export.py`
- Test: `rs3d-app/tests/core/test_export.py`

Processing order (must stay identical to the generated code in Task 6): load raw counts → if `m/s`: `remove_response(output="VEL")` → if filter: `detrend("demean")` then `filter("bandpass", corners=4, zerophase=True)`. CSV has one row per sample on a common grid; missing samples are empty cells, never zeros.

- [ ] **Step 1: Write the failing tests** – `rs3d-app/tests/core/test_export.py`:

```python
import csv

import numpy as np
import pytest
from obspy import UTCDateTime, read

from rs3d.core.export import load_processed, process, write_csv, write_mseed, write_plot
from rs3d.core.models import Selection
from tests.conftest import GAP_END, GAP_START, T_START


def sel(**kw):
    args = dict(network="AM", station="R77A7", location="00",
                start=T_START + 10, end=T_START + 20)
    args.update(kw)
    return Selection(**args)


def test_counts_without_filter_are_unchanged(store):
    s = sel()
    raw = store.load(s)
    out = load_processed(store, s)
    for a, b in zip(raw, out):
        np.testing.assert_array_equal(a.data, b.data)


def test_filter_changes_data_and_removes_mean(store):
    out = load_processed(store, sel(filter=(1.0, 10.0)))
    assert all(abs(tr.data.mean()) < 50 for tr in out)


def test_m_s_needs_inventory(store):
    with pytest.raises(ValueError, match="inventory"):
        load_processed(store, sel(units="m/s"))


def test_m_s_scales_to_small_velocities(store, inventory):
    out = load_processed(store, sel(units="m/s"), inventory)
    assert all(np.abs(tr.data).max() < 1e-3 for tr in out)


def test_process_does_not_modify_input(store):
    s = sel(filter=(1.0, 10.0))
    raw = store.load(s)
    before = raw[0].data.copy()
    process(raw, s)
    np.testing.assert_array_equal(raw[0].data, before)


def test_write_mseed_roundtrip(store, tmp_path):
    out = load_processed(store, sel())
    path = write_mseed(out, tmp_path / "x.mseed")
    back = read(str(path))
    assert sorted(tr.id for tr in back) == sorted(tr.id for tr in out)


def test_write_csv_columns_and_gap(store, tmp_path):
    s = sel(start=GAP_START - 0.05, end=GAP_END + 0.05)
    out = load_processed(store, s)
    path = write_csv(out, tmp_path / "x.csv", s.channels)
    rows = list(csv.reader(path.open()))
    assert rows[0] == ["time_utc", "EHZ", "EHN", "EHE"]
    assert rows[1][0] == "2026-10-12T00:01:59.950000Z"
    assert all(v != "" for v in rows[1][1:])
    gap_row = next(r for r in rows[1:] if r[0] == "2026-10-12T00:02:30.000000Z")
    assert gap_row[1:] == ["", "", ""]
    assert rows[-1][0] == "2026-10-12T00:03:00.050000Z"


def test_write_csv_rejects_mixed_rates(store, tmp_path):
    out = load_processed(store, sel())
    out[0].stats.sampling_rate = 50.0
    with pytest.raises(ValueError, match="sampling rate"):
        write_csv(out, tmp_path / "x.csv", ("EHZ", "EHN", "EHE"))


@pytest.mark.parametrize("suffix", [".png", ".pdf"])
def test_write_plot(store, tmp_path, suffix):
    out = load_processed(store, sel())
    path = write_plot(out, tmp_path / f"x{suffix}")
    assert path.stat().st_size > 1000


def test_write_plot_rejects_other_suffix(store, tmp_path):
    with pytest.raises(ValueError):
        write_plot(load_processed(store, sel()), tmp_path / "x.jpg")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_export.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rs3d.core.export'`

- [ ] **Step 3: Implement** – `rs3d-app/src/rs3d/core/export.py`:

```python
"""Turn a Selection into processed data and write it as miniSEED, CSV, PNG or PDF."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # the app renders files on a server, never on screen

import numpy as np
from obspy import Inventory, Stream

from rs3d.core.models import Selection
from rs3d.core.store import Store


def process(st: Stream, sel: Selection, inventory: Inventory | None = None) -> Stream:
    """Apply the selection's units and filter. Returns a new Stream; gaps stay gaps."""
    st = st.copy()
    if sel.units == "m/s":
        if inventory is None:
            raise ValueError("units 'm/s' need an instrument response (inventory)")
        st.remove_response(inventory=inventory, output="VEL")
    if sel.filter is not None:
        fmin, fmax = sel.filter
        st.detrend("demean")
        st.filter("bandpass", freqmin=fmin, freqmax=fmax, corners=4, zerophase=True)
    return st


def load_processed(store: Store, sel: Selection, inventory: Inventory | None = None) -> Stream:
    return process(store.load(sel), sel, inventory)


def write_mseed(st: Stream, path: Path) -> Path:
    st.write(str(path), format="MSEED")
    return path


def write_plot(st: Stream, path: Path) -> Path:
    """PNG or PDF, chosen by the file extension."""
    if path.suffix.lower() not in (".png", ".pdf"):
        raise ValueError("plot path must end in .png or .pdf")
    st.plot(outfile=str(path), size=(1200, 300 * max(len({tr.id for tr in st}), 1)))
    return path


def write_csv(st: Stream, path: Path, channels: tuple[str, ...]) -> Path:
    """One row per sample: time_utc, then one column per channel. Missing samples are empty."""
    rates = {tr.stats.sampling_rate for tr in st}
    if len(rates) > 1:
        raise ValueError(f"all channels need the same sampling rate, got {sorted(rates)}")
    if not st:
        path.write_text("time_utc," + ",".join(channels) + "\n", encoding="utf-8")
        return path
    rate = rates.pop()
    t0 = min(tr.stats.starttime for tr in st)
    t1 = max(tr.stats.endtime for tr in st)
    n = int(round((t1 - t0) * rate)) + 1
    table = np.full((n, len(channels)), np.nan)
    for col, channel in enumerate(channels):
        for tr in st.select(channel=channel):
            i0 = int(round((tr.stats.starttime - t0) * rate))
            table[i0:i0 + tr.stats.npts, col] = tr.data
    base = np.datetime64(t0.datetime, "us")
    times = base + (np.arange(n) * (1e6 / rate)).round().astype("timedelta64[us]")
    stamps = np.datetime_as_string(times, unit="us")
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["time_utc", *channels])
        for stamp, row in zip(stamps, table):
            w.writerow([stamp + "Z", *("" if np.isnan(v) else repr(float(v)) for v in row)])
    return path
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/core/test_export.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add rs3d-app/src/rs3d/core/export.py rs3d-app/tests/core/test_export.py
git commit -m "feat(rs3d-app): processing and miniSEED/CSV/PNG/PDF export"
```

---

### Task 6: Code generation

**Files:**
- Create: `rs3d-app/src/rs3d/core/codegen.py`
- Test: `rs3d-app/tests/core/test_codegen.py`

The generated code must give exactly the same `Stream` as `export.load_processed()`. The tests execute the generated code and compare sample by sample. Paths and values are embedded with `repr()` so quotes and Windows backslashes are safe.

- [ ] **Step 1: Write the failing tests** – `rs3d-app/tests/core/test_codegen.py`:

```python
import numpy as np
import pytest

from rs3d.core.codegen import generate
from rs3d.core.export import load_processed
from rs3d.core.models import Selection
from tests.conftest import GAP_END, GAP_START, T_START


def run(code: str):
    namespace: dict = {}
    exec(compile(code, "<generated>", "exec"), namespace)
    return namespace["st"]


def assert_same(a, b):
    a = sorted(a, key=lambda tr: (tr.id, tr.stats.starttime))
    b = sorted(b, key=lambda tr: (tr.id, tr.stats.starttime))
    assert len(a) == len(b)
    for x, y in zip(a, b):
        assert x.id == y.id and x.stats.starttime == y.stats.starttime
        np.testing.assert_array_equal(x.data, y.data)


@pytest.mark.parametrize("kw", [
    {},
    {"filter": (1.0, 10.0)},
    {"channels": ("EHZ",), "start": GAP_START - 30, "end": GAP_END + 30},
])
def test_generated_code_matches_export(store, kw):
    args = dict(network="AM", station="R77A7", location="00", start=T_START + 10, end=T_START + 40)
    args.update(kw)
    s = Selection(**args)
    assert_same(run(generate(s, store.root)), load_processed(store, s))


def test_generated_code_with_response(store, inventory, tmp_path):
    inv_path = tmp_path / "AM.R77A7.xml"
    inventory.write(str(inv_path), format="STATIONXML")
    s = Selection("AM", "R77A7", "00", T_START + 10, T_START + 40, units="m/s", filter=(1.0, 10.0))
    code = generate(s, store.root, inv_path)
    assert "read_inventory" in code
    assert_same(run(code), load_processed(store, s, inventory))


def test_m_s_without_inventory_path_is_rejected(store):
    s = Selection("AM", "R77A7", "00", T_START, T_START + 10, units="m/s")
    with pytest.raises(ValueError):
        generate(s, store.root)


def test_paths_with_quotes_and_backslashes_are_safe(store):
    s = Selection("AM", "R77A7", "00", T_START, T_START + 10)
    code = generate(s, store.root / "it's\\odd")
    compile(code, "<generated>", "exec")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_codegen.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rs3d.core.codegen'`

- [ ] **Step 3: Implement** – `rs3d-app/src/rs3d/core/codegen.py`:

```python
"""Generate ObsPy code that reproduces exactly what export.load_processed() returns."""

from __future__ import annotations

from pathlib import Path

from rs3d.core.models import Selection


def generate(sel: Selection, sds_root: Path, inventory_path: Path | None = None) -> str:
    if sel.units == "m/s" and inventory_path is None:
        raise ValueError("units 'm/s' need inventory_path")
    lines = [
        "from obspy import Stream, UTCDateTime",
        "from obspy.clients.filesystem.sds import Client",
    ]
    if sel.units == "m/s":
        lines.append("from obspy import read_inventory")
    lines += [
        "",
        f"client = Client({str(sds_root)!r})",
        f"start = UTCDateTime({str(sel.start)!r})",
        f"end = UTCDateTime({str(sel.end)!r})",
        "",
        "st = Stream()",
        f"for channel in {tuple(sel.channels)!r}:",
        f"    st += client.get_waveforms({sel.network!r}, {sel.station!r}, {sel.location!r}, channel, start, end)",
        "st.trim(start, end)",
    ]
    if sel.units == "m/s":
        lines += [
            "",
            "# counts -> ground velocity (m/s)",
            f"inv = read_inventory({str(inventory_path)!r})",
            'st.remove_response(inventory=inv, output="VEL")',
        ]
    if sel.filter is not None:
        fmin, fmax = sel.filter
        lines += [
            "",
            'st.detrend("demean")',
            f'st.filter("bandpass", freqmin={fmin!r}, freqmax={fmax!r}, corners=4, zerophase=True)',
        ]
    lines += ["", "print(st)", ""]
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/core/test_codegen.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add rs3d-app/src/rs3d/core/codegen.py rs3d-app/tests/core/test_codegen.py
git commit -m "feat(rs3d-app): generate ObsPy code matching the export"
```

---

### Task 7: Full suite

- [ ] **Step 1: Run everything**

Run: `uv run pytest -q`
Expected: `35 passed`

- [ ] **Step 2: Check nothing generated is tracked**

Run (from the repository root): `git status --short`
Expected: no output (`.venv/`, `__pycache__/` and `.pytest_cache/` are ignored).
