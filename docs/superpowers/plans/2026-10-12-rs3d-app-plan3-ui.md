# RS3D App – Plan 3: User Interface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the NiceGUI interface (layout A: left sidebar; pages Status, Live, Data, Guide, Settings; compact UI with (?) help icons) on top of the Plan 1 and Plan 2 core, plus miniSEED import so the Data page works without a Shake.

**Architecture:** `rs3d/app/` holds UI code. Logic that can be tested without a browser lives in plain modules (`strings.py`, `timeutil.py`, `charts.py` building ECharts option dicts). Pages are thin and are smoke-tested with NiceGUI's in-process `user_simulation` against a small test app (`tests/app/sim_main.py`) that fakes device access. All texts come from `rs3d/help/en.toml` and `rs3d/guide/en.md`. Spec: `docs/superpowers/specs/2026-10-12-rs3d-app-design.md` (section 5).

**Tech Stack:** NiceGUI 3.x (Quasar, ECharts), ObsPy, SciPy (live band-pass, comes with ObsPy), pytest.

**This is plan 3 of 3.** Plans 1 and 2 are merged.

---

## Context for the engineer

- **NiceGUI 3**: pages are functions decorated with `@ui.page("/path")`; query parameters arrive as function arguments. Blocking work (SSH, file IO, ObsPy) runs in `await run.io_bound(fn, ...)`; it may return `None` when the browser disconnects, so guard against it. UI elements must not be changed from worker threads: worker threads write to a plain dict and a `ui.timer` copies it to the UI.
- **ECharts** via `ui.echart(options)`: change `chart.options` then call `chart.update()`. Events are forwarded as `chart:<event>` (we use `chart:datazoom`). Time axes use the browser's time zone unless `useUTC: true`; every chart follows the UTC/Local toggle.
- **Coverage bar**: a coloured strip (`markArea` per coverage segment) plus a slider (`dataZoom`) that is the Start/End selection. The slider drives a hidden second x-axis so moving it never zooms the strip.
- **Uploads**: `ui.upload(on_upload=...)`, the handler gets `e.file` with `.name` and `await e.file.save(path)`. The uploader is hidden; a small button calls `uploader.run_method("pickFiles")`.
- **Import**: `Store.import_file()` splits any miniSEED file into SDS day files, merging with what is there. The Data page lists every station in the local store plus the current Shake; Shake-only actions (list/download the archive) run only when the selected station is the current Shake.
- Run the app: `uv run rs3d-app` (opens a browser on http://127.0.0.1:8765). `RS3D_DATA_DIR=/some/dir` uses a separate data folder; `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring` disables the OS keyring (useful for tests).

## File structure

```
rs3d-app/
├── pyproject.toml                    # + nicegui, [project.scripts] rs3d-app
├── src/rs3d/
│   ├── cli.py                        # `rs3d-app [--port N] [--no-browser]`
│   ├── help/en.toml                  # every label + every (?) text
│   ├── guide/en.md                   # Guide page content
│   ├── core/store.py                 # + stations(), channels(), import_file()
│   ├── core/live.py                  # + band-pass in snapshot(); decimation keeps gaps
│   └── app/
│       ├── __init__.py
│       ├── strings.py                # label(), help_text(), guide_markdown()
│       ├── timeutil.py               # presets, UTC/local text, zoom views, slider % -> time
│       ├── charts.py                 # ECharts option builders
│       ├── state.py                  # AppState: devices, passwords, store, live streams, settings
│       ├── widgets.py                # frame() (header + sidebar), help_icon(), level_icon(), Find Shake dialog
│       ├── main.py                   # build(state), run()
│       └── pages/{__init__,status,live,data,guide,settings}.py
└── tests/
    ├── core/test_store.py, core/test_live.py   # extended
    └── app/{__init__,test_strings,test_timeutil,test_charts,sim_main,test_pages}.py
```

All commands run from `rs3d-app/`.

---

### Task 1: Dependency, texts and guide

**Files:**
- Modify: `rs3d-app/pyproject.toml`
- Create: `rs3d-app/src/rs3d/help/en.toml`
- Create: `rs3d-app/src/rs3d/guide/en.md`
- Create: `rs3d-app/src/rs3d/app/__init__.py`
- Create: `rs3d-app/src/rs3d/app/strings.py`
- Create: `rs3d-app/tests/app/__init__.py` (empty)
- Test: `rs3d-app/tests/app/test_strings.py`

- [ ] **Step 1: Add NiceGUI and the command**

Run: `uv add "nicegui>=3.0"`

Then add this table to `pyproject.toml`, directly above `[dependency-groups]`:

```toml
[project.scripts]
rs3d-app = "rs3d.cli:main"
```

- [ ] **Step 2: Write the failing tests** – `rs3d-app/tests/app/test_strings.py`:

```python
import tomllib
from importlib import resources

from rs3d.app.strings import guide_markdown, help_text, label
from rs3d.core.status import ORDER

def test_labels_and_fallback():
    assert label("nav.status") == "Status"
    assert label("check.forwarding") == "Data Forwarding"
    assert label("does.not.exist") == "does.not.exist"


def test_help_text_falls_back_to_parent():
    short, detail = help_text("ssh.auth")
    assert "password" in short.lower() and detail
    assert help_text("ssh.nonexistent")[0] == help_text("ssh")[0]
    assert help_text("nothing") == ("", "")


def test_every_check_has_a_label_and_help():
    for check_id in ORDER:
        assert label(f"check.{check_id}") != f"check.{check_id}"
        assert help_text(check_id)[0]


def test_every_help_id_used_by_status_exists():
    ids = ["ssh.auth", "ssh.unreachable", "ssh.hostkey", "ssh.command", "clock.offset", "clock.nosource",
           "wifi.duplicate", "archive.none", "archive.atrisk", "unreadable"]
    data = tomllib.loads(resources.files("rs3d").joinpath("help", "en.toml").read_text())
    for hid in ids:
        node = data["help"]
        for part in hid.split("."):
            node = node[part]
        assert node["short"]


def test_guide_is_bundled():
    assert guide_markdown().startswith("# RS3D Guide")
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/app/test_strings.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rs3d.app'`

- [ ] **Step 4: Create the texts** – `rs3d-app/src/rs3d/help/en.toml`:

```toml
# All user-facing text of rs3d-app (English). Add vi.toml / pt.toml with the same keys later.
# [labels] = short UI labels. [help.<id>] = text behind a (?) icon: short = tooltip, detail = Markdown panel.

[labels]
app = "RS3D"
devices = "Devices"
find = "Find Shake…"
no_device = "No Shake yet. Plug the cable in and use Find Shake…, or add one in Settings."

[labels.nav]
status = "Status"
live = "Live"
data = "Data"
guide = "Guide"
settings = "Settings"

[labels.check]
laptop_ip = "Laptop IP"
seedlink = "SeedLink"
channels = "Channels"
ssh = "SSH"
clock = "Clock"
internet = "Internet"
wifi = "Wi-Fi"
storage = "Storage"
archive = "Archive"
forwarding = "Data Forwarding"
password = "Password"

[labels.action]
refresh = "Refresh"
set_ip = "Set IP"
download = "Download"
run = "Run"
cancel = "Cancel"
close = "Close"
add = "Add"
save = "Save"
remove = "Remove"
test = "Test connection"
pause = "Pause"
resume = "Resume"
save_segment = "Save this segment"
download_preview = "Download & preview"
preview = "Preview"
copy = "Copy"
save_py = "Save .py"

[labels.live]
window = "Window"
filter = "Filter"
live = "live"
connecting = "connecting…"
reconnecting = "reconnecting…"
waiting = "waiting for data…"
stopped = "stopped"

[labels.data]
start = "Start"
end = "End"
presets = "Presets"
utc = "UTC"
local = "Local"
week = "Week"
day = "Day"
hour = "Hour"
files_needed = "Files to download"
channels = "Channels"
filter = "Band-pass"
units = "Units"
preview = "Preview"
export = "Export"
code = "Code"
nothing = "No data in this range."
downloading = "Downloading"
bad_time = "Use YYYY-MM-DD hh:mm:ss"
station = "Station"
import = "Import miniSEED"
imported = "Imported"
empty = "No data yet. Connect a Shake, or import a miniSEED file."

[labels.preset]
last_10_min = "Last 10 min"
last_hour = "Last hour"
today = "Today"
yesterday = "Yesterday"
last_7_days = "Last 7 days"

[labels.settings]
device = "Device"
name = "Name"
host = "IP / host name"
port = "SeedLink port"
user = "SSH user"
password = "SSH password"
key = "SSH key file (optional)"
app = "App"
timezone = "Time shown as"
data_dir = "Data folder"
saved = "Saved"
ok = "Connection OK"
new = "New device"

[labels.setip]
title = "Give this laptop a 169.254.x.x address"
interface = "Wired interface"
commands = "Commands that will run"
done = "Done. Checking again…"

# ---------------------------------------------------------------- (?) texts

[help.laptop_ip]
short = "The laptop needs a 169.254.x.x address on the cable to reach the Shake."
detail = """
The Shake has no DHCP server on the cable, so both sides use **link-local** addresses (`169.254.x.x`).

**Fix:** press **Set IP**. The app asks your OS for permission, then lets it pick a free link-local address:

- Linux: `nmcli connection modify <connection> ipv4.link-local enabled`
- Windows: switch the Ethernet adapter to DHCP (Windows then self-assigns 169.254.x.x)
- macOS: `networksetup -setdhcp <service>`

Check that the cable is plugged in and the Shake is powered.
"""

[help.seedlink]
short = "Live data port of the Shake (TCP 18000)."
detail = """
The app reads live data with **SeedLink** on port 18000.

If this fails: check the cable, wait 3–5 minutes after powering the Shake, and check the IP in **Settings**.
"""

[help.channels]
short = "Channels served by the Shake. An RS3D has EHZ, EHN and EHE."
detail = "EHZ = vertical, EHN = north–south, EHE = east–west, 100 samples per second."

[help.ssh]
short = "The app logs in (read-only) to read clock, storage and archive."
detail = """
SSH (port 22) with the user and password from **Settings**. The app never changes anything on the Shake.
"""

[help.ssh.auth]
short = "Wrong user name, password or key."
detail = "Open **Settings**, enter the Shake's SSH password (default `shakeme` unless changed) and press **Test connection**."

[help.ssh.unreachable]
short = "Cannot reach the Shake on port 22."
detail = "Check the cable and the IP in **Settings**. SSH must be enabled on the Shake (it is by default)."

[help.ssh.hostkey]
short = "The Shake's identity changed."
detail = """
The Shake answered with a different SSH host key than before. This is normal after re-installing the Shake's SD card.

If that is the case, delete the line for this IP from the app's `known_hosts` file in the data folder (see **Settings**) and refresh.
"""

[help.ssh.command]
short = "A read command failed on the Shake."
detail = "Refresh. If it keeps failing, the Shake software may be different from the tested version (Shake OS 0.21)."

[help.clock]
short = "Time offset of the Shake and its time source (ntpq)."
detail = """
Seismic timestamps come from the Shake's clock, kept right by **ntpd**.

- Internet servers via Wi-Fi (current setup), or
- the laptop (`169.254.8.11`) as a backup, or
- a USB GPS (planned).
"""

[help.clock.offset]
short = "The Shake clock is off by more than 100 ms."
detail = "Data timestamps are unreliable. Check Internet / Wi-Fi on the Shake (see **Internet**) and wait a few minutes for ntpd."

[help.clock.nosource]
short = "The Shake has no time source."
detail = """
`ntpq -p` shows no selected server (`*`). Without one the clock drifts, and after a power cut it restarts from an old time.

Fix Internet on the Shake (see **Internet** and **Wi-Fi**) or connect the laptop that serves time.
"""

[help.internet]
short = "Whether the Shake reaches the Internet (needed for its clock)."
detail = "The Shake uses Wi-Fi for Internet time. Data still flows to the laptop over the cable without Internet."

[help.wifi]
short = "The Shake's Wi-Fi address."
detail = "Wi-Fi is used only for Internet time. The app always talks to the Shake over the cable."

[help.wifi.duplicate]
short = "Two Wi-Fi addresses: Internet will come and go."
detail = """
Two DHCP clients manage `wlan0` on the Shake. See **Guide → Wi-Fi: two addresses**.

Fix (on the Shake): move `denyinterfaces wlan0` to the top of `/etc/dhcpcd.conf`, then reboot.
"""

[help.storage]
short = "Free space on the Shake's SD card."
detail = "The Shake needs space for its archive (about 85 MB per day)."

[help.archive]
short = "Days stored on the Shake, and how long it keeps them."
detail = """
The Shake writes one miniSEED file per channel per day and deletes days older than its retention (`archkeep`, 7 days here).

Download data at least once a week, or raise the retention in the Shake web page.
"""

[help.archive.none]
short = "No archive found on the Shake."
detail = "Archiving may be disabled in the Shake web settings. Live data still works."

[help.archive.atrisk]
short = "Some days will soon be deleted on the Shake and are not downloaded."
detail = "Open **Data**, select those days and press **Download & preview**."

[help.forwarding]
short = "Whether the Shake shares data publicly with Raspberry Shake."
detail = "When ON and the Shake has Internet, its data and location are public on ShakeNet. Turn it off in the Shake web settings (Data Sharing)."

[help.password]
short = "Whether the Shake still uses the default password."
detail = "Change it: SSH into the Shake and run `passwd`, then update the password in **Settings**."

[help.unreadable]
short = "Unexpected answer from the Shake."
detail = "Refresh. If it persists, the Shake software may differ from the tested version."

[help.import]
short = "Add a miniSEED file (any station) to this laptop's data folder."
detail = """
The file is split into one file per channel per day (SDS layout) in the data folder, next to data downloaded from Shakes.

Importing the same file twice changes nothing. Data from other stations appears in the **Station** list.
"""

[help.timezone]
short = "Show times in UTC or in this laptop's time zone. Files and code always use UTC."
detail = "Seismic data is always stored in UTC. The Local option only changes what you see and type."

[help.presets]
short = "Quick time ranges."
detail = "\"Today\" and \"Yesterday\" follow the time zone shown (UTC or Local)."

[help.coverage]
short = "Green: on this laptop. Grey: only on the Shake. Red: no data."
detail = """
- Drag in the lower bar to select a range; drag its handles to change Start/End; drag the middle to move it.
- Week / Day / Hour and ◀ ▶ change the visible span.
- Start/End fields and the selection always follow each other.
"""

[help.files_needed]
short = "Day files that will be copied from the Shake before preview."
detail = "Today's file is always copied again because the Shake keeps writing to it."

[help.units]
short = "counts = raw digitizer values; m/s = ground velocity."
detail = """
m/s needs the instrument response. The app downloads it once from the Raspberry Shake service (laptop needs Internet that time) and keeps it.
"""

[help.code]
short = "ObsPy code that reproduces this exact export."
detail = "It reads from this laptop's data folder, so it runs without the Shake."

[help.live_filter]
short = "Band-pass 1–10 Hz to hide slow drift and high-frequency noise."
detail = "Applied only to the display. Use the Data page to export filtered data."
```

`rs3d-app/src/rs3d/guide/en.md` (note: this file contains fenced code blocks):

````markdown
# RS3D Guide

Short version of the project Manual (`docs/Manual.odt`). The Status page tells you which section you need.

## 1. Connect

1. Put the Shake on a solid, level floor, away from doors, fans and footsteps.
2. Connect the Shake's Ethernet port directly to the laptop with a cable.
3. Power the Shake and wait 3–5 minutes.
4. Open **Status**. If **Laptop IP** is red, press **Set IP**.

The Shake gives itself a `169.254.x.x` address (ours: `169.254.221.62`, name `rs.local`).

## 2. Add the Shake to the app

- Use **Find Shake…** in the sidebar, or
- open **Settings**, enter the IP, the SSH user (`myshake`) and password, then **Test connection**.

The password is stored in your operating system's password store, never in a file.

## 3. Status checks

| Check | Meaning |
|---|---|
| Laptop IP | the laptop has a `169.254.x.x` address on the cable |
| SeedLink | live data port 18000 answers |
| Channels | EHZ, EHN, EHE are served |
| SSH | the app can log in to read clock, storage and archive |
| Clock | time offset and time source of the Shake |
| Internet / Wi-Fi | the Shake reaches the Internet (for its clock) |
| Storage | free space on the Shake's SD card |
| Archive | days stored on the Shake, retention (7 days) |
| Data Forwarding | public data sharing is off |
| Password | the default password was changed |

Hover a **(?)** for a hint, click it for the full explanation and fix.

## 4. Live

Three channels in real time. Choose the window (30 s, 60 s, 5 min), switch the 1–10 Hz filter on or off, pause, and use **Save this segment** to open the same range on the Data page.

## 5. Data

1. Choose **Start** and **End**, use **Presets**, or drag on the coverage bar.
2. **Download & preview** copies the needed day files from the Shake.
3. Choose channels, band-pass filter and units (counts or m/s).
4. Export as **miniSEED**, **CSV**, **PNG**, **PDF**, or get the **Code** (ObsPy) to reproduce it.

The Shake keeps only **7 days**: download at least once a week.

## 6. Clock

The Shake keeps time with `ntpd`, from Internet servers over Wi-Fi, with the laptop (`169.254.8.11`) as a backup. Check on the Shake:

```
ntpq -pn
```

A line starting with `*` is the selected source; `offset` is in milliseconds.

## Wi-Fi: two addresses

If `ip -4 addr show wlan0` on the Shake lists two addresses, Internet comes and goes. Two DHCP clients manage `wlan0`. Fix on the Shake:

```
sudo cp -p /etc/dhcpcd.conf /etc/dhcpcd.conf.bak-rs3d
sudo sed -i '/^denyinterfaces wlan0$/d' /etc/dhcpcd.conf
sudo sed -i '1i denyinterfaces wlan0' /etc/dhcpcd.conf
sudo reboot
```

Saving network settings in the Shake web page may bring the problem back.
````

- [ ] **Step 5: Implement** – `rs3d-app/src/rs3d/app/__init__.py`:

```python
"""NiceGUI user interface."""
```

`rs3d-app/src/rs3d/app/strings.py`:

```python
"""Every user-facing text comes from rs3d/help/<lang>.toml and rs3d/guide/<lang>.md (English only in v1)."""

from __future__ import annotations

import tomllib
from functools import lru_cache
from importlib import resources


@lru_cache(maxsize=4)
def _load(lang: str) -> dict:
    return tomllib.loads(resources.files("rs3d").joinpath("help", f"{lang}.toml").read_text(encoding="utf-8"))


def label(key: str, lang: str = "en") -> str:
    """Short UI label, e.g. label('nav.status') -> 'Status'. Unknown keys show the key itself."""
    node = _load(lang).get("labels", {})
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return key
        node = node[part]
    return node if isinstance(node, str) else key


def help_text(help_id: str, lang: str = "en") -> tuple[str, str]:
    """(tooltip, detail markdown) for a (?) icon. 'ssh.auth' falls back to 'ssh' when missing."""
    entries = _load(lang).get("help", {})
    candidates = [help_id]
    while "." in candidates[-1]:
        candidates.append(candidates[-1].rsplit(".", 1)[0])
    for cid in candidates:
        node = entries
        for part in cid.split("."):
            node = node.get(part, {}) if isinstance(node, dict) else {}
        if isinstance(node, dict) and "short" in node:
            return node["short"], node.get("detail", node["short"])
    return "", ""


def guide_markdown(lang: str = "en") -> str:
    return resources.files("rs3d").joinpath("guide", f"{lang}.md").read_text(encoding="utf-8")
```

- [ ] **Step 6: Run to verify they pass**

Run: `uv run pytest tests/app/test_strings.py -v`
Expected: 5 passed

- [ ] **Step 7: Commit**

```bash
git add rs3d-app/pyproject.toml rs3d-app/uv.lock rs3d-app/src/rs3d/help rs3d-app/src/rs3d/guide rs3d-app/src/rs3d/app/__init__.py rs3d-app/src/rs3d/app/strings.py rs3d-app/tests/app/__init__.py rs3d-app/tests/app/test_strings.py
git commit -m "feat(rs3d-app): NiceGUI dependency, English texts and guide"
```

---

### Task 2: Time helpers

**Files:**
- Create: `rs3d-app/src/rs3d/app/timeutil.py`
- Test: `rs3d-app/tests/app/test_timeutil.py`

- [ ] **Step 1: Write the failing tests** – `rs3d-app/tests/app/test_timeutil.py`:

```python
from datetime import timedelta

import pytest
from obspy import UTCDateTime

from rs3d.app import timeutil

NOW = UTCDateTime("2026-10-12T17:30:45")
LISBON = timedelta(hours=1)

def test_text_roundtrip_utc_and_local():
    t = UTCDateTime("2026-10-12T17:30:45")
    assert timeutil.to_text(t, False) == "2026-10-12 17:30:45"
    assert timeutil.to_text(t, True, LISBON) == "2026-10-12 18:30:45"
    assert timeutil.from_text("2026-10-12 18:30:45", True, LISBON) == t
    with pytest.raises(ValueError):
        timeutil.from_text("12/10/2026", False)


@pytest.mark.parametrize("name, start, end", [
    ("last_10_min", "2026-10-12T17:20:45", "2026-10-12T17:30:45"),
    ("last_hour", "2026-10-12T16:30:45", "2026-10-12T17:30:45"),
    ("today", "2026-10-12T00:00:00", "2026-10-12T17:30:45"),
    ("yesterday", "2026-10-11T00:00:00", "2026-10-12T00:00:00"),
    ("last_7_days", "2026-10-05T17:30:45", "2026-10-12T17:30:45"),
])
def test_presets_utc(name, start, end):
    assert timeutil.preset_range(name, NOW, False) == (UTCDateTime(start), UTCDateTime(end))


def test_today_follows_local_zone():
    late = UTCDateTime("2026-10-12T23:30:00")  # already 13 Oct 00:30 in Lisbon
    a, b = timeutil.preset_range("today", late, True, LISBON)
    assert a == UTCDateTime("2026-10-12T23:00:00") and b == late


def test_view_ranges_and_shift():
    assert timeutil.view_range("day", NOW) == (UTCDateTime("2026-10-12"), UTCDateTime("2026-10-13"))
    assert timeutil.view_range("hour", NOW) == (UTCDateTime("2026-10-12T17:00"), UTCDateTime("2026-10-12T18:00"))
    assert timeutil.view_range("week", NOW)[0] == UTCDateTime("2026-10-06")
    center = timeutil.shift_view("day", UTCDateTime("2026-10-12"), -1)
    assert timeutil.view_range("day", center)[0] == UTCDateTime("2026-10-11")


def test_percent_to_time():
    view = (UTCDateTime("2026-10-12"), UTCDateTime("2026-10-13"))
    assert timeutil.percent_to_time(view, 50) == UTCDateTime("2026-10-12T12:00:00")
    assert timeutil.percent_to_time(view, 150) == view[1]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/app/test_timeutil.py -v`
Expected: FAIL with `ImportError: cannot import name 'timeutil' from 'rs3d.app'`

- [ ] **Step 3: Implement** – `rs3d-app/src/rs3d/app/timeutil.py`:

```python
"""Time helpers for the Data page: presets, display time zone, slider percent <-> time."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from obspy import UTCDateTime

FORMAT = "%Y-%m-%d %H:%M:%S"
PRESETS = ("last_10_min", "last_hour", "today", "yesterday", "last_7_days")


def local_offset(now: datetime | None = None) -> timedelta:
    now = now or datetime.now().astimezone()
    return now.utcoffset() or timedelta(0)


def to_text(t: UTCDateTime, use_local: bool, offset: timedelta | None = None) -> str:
    dt = t.datetime
    if use_local:
        dt += offset if offset is not None else local_offset()
    return dt.strftime(FORMAT)


def from_text(text: str, use_local: bool, offset: timedelta | None = None) -> UTCDateTime:
    """Parse 'YYYY-MM-DD hh:mm:ss' typed in the display zone; raises ValueError if malformed."""
    dt = datetime.strptime(text.strip(), FORMAT)
    if use_local:
        dt -= offset if offset is not None else local_offset()
    return UTCDateTime(dt.replace(tzinfo=timezone.utc))


def preset_range(name: str, now: UTCDateTime, use_local: bool,
                 offset: timedelta | None = None) -> tuple[UTCDateTime, UTCDateTime]:
    """(start, end) in UTC. 'today'/'yesterday' follow the displayed time zone."""
    now = UTCDateTime(int(now.timestamp))  # whole seconds
    if name == "last_10_min":
        return now - 600, now
    if name == "last_hour":
        return now - 3600, now
    if name == "last_7_days":
        return now - 7 * 86400, now
    shift = (offset if offset is not None else local_offset()).total_seconds() if use_local else 0.0
    local_now = now + shift
    midnight = UTCDateTime(local_now.year, local_now.month, local_now.day) - shift
    if name == "today":
        return midnight, now
    if name == "yesterday":
        return midnight - 86400, midnight
    raise ValueError(f"unknown preset {name!r}")


def view_range(level: str, center: UTCDateTime) -> tuple[UTCDateTime, UTCDateTime]:
    """Visible span of the coverage bar for zoom level week | day | hour, in UTC."""
    if level == "hour":
        start = UTCDateTime(center.year, center.month, center.day, center.hour)
        return start, start + 3600
    day = UTCDateTime(center.year, center.month, center.day)
    if level == "day":
        return day, day + 86400
    if level == "week":
        return day - 6 * 86400, day + 86400
    raise ValueError(f"unknown zoom level {level!r}")


def shift_view(level: str, start: UTCDateTime, direction: int) -> UTCDateTime:
    """New center after ◀ (-1) or ▶ (+1)."""
    step = {"hour": 3600, "day": 86400, "week": 7 * 86400}[level]
    return start + direction * step + step / 2


def percent_to_time(view: tuple[UTCDateTime, UTCDateTime], percent: float) -> UTCDateTime:
    a, b = view
    return UTCDateTime(int((a + (b - a) * max(0.0, min(100.0, percent)) / 100).timestamp))
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/app/test_timeutil.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add rs3d-app/src/rs3d/app/timeutil.py rs3d-app/tests/app/test_timeutil.py
git commit -m "feat(rs3d-app): time presets, zones and coverage views"
```

---

### Task 3: Core additions – miniSEED import, live band-pass, gap-safe decimation

**Files:**
- Modify (replace whole file): `rs3d-app/src/rs3d/core/store.py`
- Modify (replace whole file): `rs3d-app/src/rs3d/core/live.py`
- Modify (replace whole file): `rs3d-app/tests/core/test_store.py`
- Modify (replace whole file): `rs3d-app/tests/core/test_live.py`

New behaviour: `Store.stations()`, `Store.channels()`, `Store.import_file()`; `RingBuffer.snapshot(..., bandpass=(fmin, fmax))` filters each contiguous chunk before decimation; decimation now works per contiguous segment so the NaN gap marker is never lost (this was a bug: a bin mixing a gap and samples dropped the marker and charts joined the line across the gap).

- [ ] **Step 1: Replace the tests** – `rs3d-app/tests/core/test_store.py`:

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


def test_stations_and_channels(store):
    assert store.stations() == [("AM", "R77A7", "00")]
    assert store.channels("AM", "R77A7", "00") == ["EHZ", "EHN", "EHE"]


def test_import_file_splits_by_day_and_merges(tmp_path, store):
    from obspy import read as obspy_read

    one_file = tmp_path / "all.mseed"
    st = obspy_read(str(store.day_path("AM", "R77A7", "00", "EHZ", DAY1)))
    st += obspy_read(str(store.day_path("AM", "R77A7", "00", "EHZ", DAY2)))
    st.merge(method=-1)
    st.write(str(one_file), format="MSEED")

    fresh = Store(tmp_path / "fresh")
    written = fresh.import_file(one_file)
    assert {p.name for p in written} == {"AM.R77A7.00.EHZ.D.2026.284", "AM.R77A7.00.EHZ.D.2026.285"}
    sel = Selection("AM", "R77A7", "00", GAP_START - 30, GAP_END + 30, channels=("EHZ",))
    assert len(fresh.load(sel)) == 2  # gap preserved

    fresh.import_file(one_file)  # importing twice changes nothing
    again = fresh.load(sel)
    assert len(again) == 2 and sum(tr.stats.npts for tr in again) == sum(tr.stats.npts for tr in store.load(sel))
```

`rs3d-app/tests/core/test_live.py`:

```python
import threading

import numpy as np
from obspy import Trace, UTCDateTime

from rs3d.core.live import BACKOFF, LiveStream, RingBuffer

T0 = UTCDateTime("2026-10-12T12:00:00")


def trace(channel, start, n, rate=100.0, value=1.0):
    return Trace(np.full(n, value), header={"channel": channel, "starttime": start, "sampling_rate": rate})


def test_contiguous_packets_merge():
    buf = RingBuffer()
    buf.add(trace("EHZ", T0, 100))
    buf.add(trace("EHZ", T0 + 1, 100))
    t, v = buf.snapshot("EHZ", 10)
    assert len(t) == 200 and not np.isnan(v).any()
    assert buf.latest() == (T0 + 2).timestamp


def test_gap_is_marked_with_nan():
    buf = RingBuffer()
    buf.add(trace("EHZ", T0, 100))
    buf.add(trace("EHZ", T0 + 5, 100))
    t, v = buf.snapshot("EHZ", 10)
    assert np.isnan(v).sum() == 1 and len(t) == 201


def test_old_data_is_dropped():
    buf = RingBuffer(seconds=60)
    buf.add(trace("EHZ", T0, 100))
    buf.add(trace("EHZ", T0 + 120, 100))
    t, _ = buf.snapshot("EHZ", 600)
    assert t.min() >= (T0 + 120).timestamp


def test_snapshot_window_and_unknown_channel():
    buf = RingBuffer()
    buf.add(trace("EHZ", T0, 1000))
    t, _ = buf.snapshot("EHZ", 2)
    assert len(t) == 200 and t[-1] < (T0 + 10).timestamp
    assert buf.snapshot("EHN", 2)[0].size == 0


def test_decimation_keeps_peaks():
    buf = RingBuffer()
    data = np.zeros(30000)
    data[12345] = 999.0
    buf.add(Trace(data, header={"channel": "EHZ", "starttime": T0, "sampling_rate": 100.0}))
    t, v = buf.snapshot("EHZ", 300, max_points=1000)
    assert len(t) <= 1000 and v.max() == 999.0


class FakeSource:
    def __init__(self, traces, fail=None):
        self.traces, self.fail, self.closed = traces, fail, False

    def run(self, on_trace):
        for tr in self.traces:
            on_trace(tr)
        if self.fail:
            raise self.fail

    def close(self):
        self.closed = True


def test_reconnects_with_backoff_and_resets_after_success():
    sleeps, made = [], []
    stop_after = threading.Event()

    def factory():
        n = len(made)
        if n in (0, 1):
            src = FakeSource([], fail=ConnectionRefusedError("refused"))
        elif n == 2:
            src = FakeSource([trace("EHZ", T0, 100)], fail=ConnectionResetError("cable"))
        else:
            stop_after.set()
            src = FakeSource([], fail=ConnectionRefusedError("refused"))
        made.append(src)
        return src

    live = LiveStream(factory, sleep=lambda s: sleeps.append(s))
    live.start()
    assert stop_after.wait(5)
    live.stop()
    assert sleeps[:3] == [BACKOFF[0], BACKOFF[1], BACKOFF[0]]
    assert live.buffer.snapshot("EHZ", 10)[0].size == 100
    assert live.state == "stopped"


def test_is_stale_before_any_data():
    live = LiveStream(lambda: FakeSource([]))
    assert live.is_stale()


def test_bandpass_removes_offset_and_keeps_gap():
    buf = RingBuffer()
    t = np.arange(1000) / 100.0
    wave = 1000.0 + 50 * np.sin(2 * np.pi * 5 * t)  # 5 Hz on a big offset
    buf.add(Trace(wave, header={"channel": "EHZ", "starttime": T0, "sampling_rate": 100.0}))
    buf.add(Trace(wave, header={"channel": "EHZ", "starttime": T0 + 20, "sampling_rate": 100.0}))
    _, raw = buf.snapshot("EHZ", 30)
    _, flt = buf.snapshot("EHZ", 30, bandpass=(1.0, 10.0))
    assert np.nanmean(raw) > 900 and abs(np.nanmean(flt)) < 5
    assert np.isnan(flt).sum() == 1
    assert 40 < np.nanmax(flt) < 60


def test_decimation_keeps_gap_marker():
    buf = RingBuffer()
    buf.add(trace("EHZ", T0, 3000))
    buf.add(trace("EHZ", T0 + 60, 3000))
    t, v = buf.snapshot("EHZ", 90, max_points=200)
    assert len(t) <= 201 and np.isnan(v).sum() == 1
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `uv run pytest tests/core/test_store.py tests/core/test_live.py -v`
Expected: 4 failures: `test_stations_and_channels`, `test_import_file_splits_by_day_and_merges` (AttributeError: 'Store' object has no attribute ...), `test_bandpass_removes_offset_and_keeps_gap` (TypeError: unexpected keyword argument 'bandpass'), `test_decimation_keeps_gap_marker` (AssertionError on the NaN count). All other tests pass.

- [ ] **Step 3: Implement** – replace `rs3d-app/src/rs3d/core/store.py`:

```python
"""Local SDS (SeisComP Data Structure) store of miniSEED day files."""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from obspy import Stream, UTCDateTime, read
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

    def stations(self) -> list[tuple[str, str, str]]:
        """(network, station, location) of everything in the store, sorted."""
        found = set()
        for path in self.root.glob("*/*/*/*.D/*"):
            m = _DAY_FILE.match(path.name)
            if m:
                found.add((m["net"], m["sta"], m["loc"]))
        return sorted(found)

    def channels(self, network: str, station: str, location: str) -> list[str]:
        found = set()
        for path in self.root.glob(f"*/{network}/{station}/*.D/*"):
            m = _DAY_FILE.match(path.name)
            if m and m["loc"] == location:
                found.add(m["cha"])
        order = {"Z": 0, "N": 1, "E": 2}
        return sorted(found, key=lambda c: (order.get(c[-1:], 9), c))

    def import_file(self, path: Path | str) -> list[Path]:
        """Copy any miniSEED file into the store, split into SDS day files.

        Data already in the store for the same channel and day is kept; overlapping
        samples are merged (identical overlaps collapse, gaps stay gaps).
        """
        st = read(str(path))
        written = []
        for tr_id in sorted({tr.id for tr in st}):
            part = st.select(id=tr_id)
            first = min(tr.stats.starttime for tr in part).date
            last = max(tr.stats.endtime for tr in part).date
            net, sta, loc, cha = tr_id.split(".")
            day = first
            while day <= last:
                start = UTCDateTime(day.year, day.month, day.day)
                piece = part.slice(start, start + 86400 - 1e-6).copy()
                if piece:
                    target = self.day_path(net, sta, loc, cha, day)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        piece += read(str(target))
                        piece.merge(method=1)
                    piece.split().write(str(target), format="MSEED")
                    written.append(target)
                day += timedelta(days=1)
        return written
```

Replace `rs3d-app/src/rs3d/core/live.py`:

```python
"""Live data: a background thread feeds a ring buffer; the UI takes snapshots."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Protocol

import numpy as np
from obspy import Trace, UTCDateTime

BACKOFF = (2, 4, 8, 16, 30)  # seconds between reconnect attempts


class Source(Protocol):
    def run(self, on_trace: Callable[[Trace], None]) -> None: ...
    def close(self) -> None: ...


@dataclass
class _Chunk:
    start: float  # epoch seconds of the first sample
    rate: float
    data: np.ndarray

    @property
    def end(self) -> float:  # time just after the last sample
        return self.start + len(self.data) / self.rate


class RingBuffer:
    """Recent samples per channel, as a list of contiguous chunks. Thread-safe."""

    def __init__(self, seconds: float = 600.0) -> None:
        self.seconds = seconds
        self._chunks: dict[str, list[_Chunk]] = {}
        self._lock = threading.Lock()

    def add(self, tr: Trace) -> None:
        chunk = _Chunk(tr.stats.starttime.timestamp, tr.stats.sampling_rate, tr.data.astype(float))
        with self._lock:
            chunks = self._chunks.setdefault(tr.stats.channel, [])
            last = chunks[-1] if chunks else None
            if last and abs(chunk.start - last.end) <= 0.5 / chunk.rate and last.rate == chunk.rate:
                last.data = np.concatenate([last.data, chunk.data])
            else:
                chunks.append(chunk)
            horizon = chunk.end - self.seconds
            self._chunks[tr.stats.channel] = [c for c in chunks if c.end > horizon]

    def latest(self) -> float | None:
        with self._lock:
            ends = [cs[-1].end for cs in self._chunks.values() if cs]
        return max(ends) if ends else None

    def snapshot(self, channel: str, seconds: float, end: float | None = None,
                 max_points: int = 2000, bandpass: tuple[float, float] | None = None,
                 ) -> tuple[np.ndarray, np.ndarray]:
        """(times, values) for the last `seconds` before `end`. A NaN separates non-contiguous chunks.

        `bandpass` filters each contiguous chunk on its own (zero-phase, 4 poles) before
        long windows are decimated by min/max pairs, so peaks stay visible.
        """
        end = end if end is not None else (self.latest() or time.time())
        start = end - seconds
        times, values = [], []
        with self._lock:
            chunks = list(self._chunks.get(channel, []))
        for c in chunks:
            if c.end <= start or c.start >= end:
                continue
            i0 = max(0, int(np.ceil((start - c.start) * c.rate)))
            i1 = min(len(c.data), int(np.floor((end - c.start) * c.rate)))
            if i1 <= i0:
                continue
            t = c.start + np.arange(i0, i1) / c.rate
            v = c.data[i0:i1]
            if bandpass is not None:
                v = _bandpass(v, c.rate, *bandpass)
            if times:
                times.append(np.array([t[0]]))
                values.append(np.array([np.nan]))
            times.append(t)
            values.append(v)
        if not times:
            return np.array([]), np.array([])
        t, v = np.concatenate(times), np.concatenate(values)
        if len(t) > max_points:
            t, v = _minmax_decimate(t, v, max_points)
        return t, v


def _bandpass(v: np.ndarray, rate: float, fmin: float, fmax: float) -> np.ndarray:
    """Zero-phase Butterworth band-pass of one contiguous chunk; too-short chunks are only demeaned."""
    from scipy.signal import butter, sosfiltfilt

    v = v - v.mean()
    sos = butter(2, [fmin, min(fmax, 0.45 * rate)], btype="bandpass", fs=rate, output="sos")
    padlen = 3 * (2 * len(sos) + 1)
    return sosfiltfilt(sos, v) if len(v) > padlen else v


def _minmax_decimate(t: np.ndarray, v: np.ndarray, max_points: int) -> tuple[np.ndarray, np.ndarray]:
    """Keep min and max of each bin. Each contiguous segment (between NaN markers) is decimated
    on its own, so gaps survive."""
    breaks = np.flatnonzero(np.isnan(v))
    bounds = np.concatenate([[-1], breaks, [len(v)]])
    segments = [(a + 1, b) for a, b in zip(bounds[:-1], bounds[1:]) if b > a + 1]
    total = sum(b - a for a, b in segments)
    out_t: list[float] = []
    out_v: list[float] = []
    for k, (a, b) in enumerate(segments):
        if k:
            out_t.append(t[a - 1])
            out_v.append(np.nan)
        bins = max(1, int(max_points // 2 * (b - a) / total))
        edges = np.linspace(a, b, bins + 1).astype(int)
        for lo_edge, hi_edge in zip(edges[:-1], edges[1:]):
            if hi_edge <= lo_edge:
                continue
            seg = v[lo_edge:hi_edge]
            lo, hi = lo_edge + int(np.argmin(seg)), lo_edge + int(np.argmax(seg))
            for i in sorted({lo, hi}):
                out_t.append(t[i])
                out_v.append(v[i])
    return np.array(out_t), np.array(out_v)


class LiveStream:
    """Keeps a Source running in a daemon thread; reconnects with backoff when it fails."""

    def __init__(self, source_factory: Callable[[], Source], buffer: RingBuffer | None = None,
                 sleep: Callable[[float], None] | None = None) -> None:
        self.buffer = buffer or RingBuffer()
        self.state = "stopped"  # stopped | connecting | live | reconnecting
        self.error = ""
        self.last_data: float | None = None  # time.monotonic() of the last trace
        self._factory = source_factory
        self._stop = threading.Event()
        self._sleep = sleep or (lambda s: self._stop.wait(s))
        self._thread: threading.Thread | None = None
        self._source: Source | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="rs3d-live", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._source:
            self._source.close()
        if self._thread:
            self._thread.join(timeout)
        self.state = "stopped"

    def _on_trace(self, tr: Trace) -> None:
        self.state = "live"
        self.last_data = time.monotonic()
        self.buffer.add(tr)

    def is_stale(self, seconds: float = 5.0) -> bool:
        """True when no data arrived recently (ObsPy may be reconnecting inside the source)."""
        return self.last_data is None or time.monotonic() - self.last_data > seconds

    def _loop(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            self.state = "connecting" if attempt == 0 else "reconnecting"
            try:
                self._source = self._factory()
                self._source.run(self._on_trace)
                self.error = "connection closed"
            except Exception as exc:
                self.error = str(exc) or type(exc).__name__
            if self._stop.is_set():
                break
            if self.state == "live":
                attempt = 0  # it worked for a while: start the backoff again
            delay = BACKOFF[min(attempt, len(BACKOFF) - 1)]
            attempt += 1
            self.state = "reconnecting"
            self._sleep(delay)
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/core/test_store.py tests/core/test_live.py -v`
Expected: 15 passed (6 + 9)

- [ ] **Step 5: Commit**

```bash
git add rs3d-app/src/rs3d/core/store.py rs3d-app/src/rs3d/core/live.py rs3d-app/tests/core/test_store.py rs3d-app/tests/core/test_live.py
git commit -m "feat(rs3d-app): miniSEED import, live band-pass, gap-safe decimation"
```

---

### Task 4: Chart option builders

**Files:**
- Create: `rs3d-app/src/rs3d/app/charts.py`
- Test: `rs3d-app/tests/app/test_charts.py`

- [ ] **Step 1: Write the failing tests** – `rs3d-app/tests/app/test_charts.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/app/test_charts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rs3d.app.charts'`

- [ ] **Step 3: Implement** – `rs3d-app/src/rs3d/app/charts.py`:

```python
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
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/app/test_charts.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add rs3d-app/src/rs3d/app/charts.py rs3d-app/tests/app/test_charts.py
git commit -m "feat(rs3d-app): ECharts builders for waveforms and coverage"
```

---

### Task 5: App state, widgets, pages and the `rs3d-app` command

**Files:**
- Create: `rs3d-app/src/rs3d/app/state.py`
- Create: `rs3d-app/src/rs3d/app/widgets.py`
- Create: `rs3d-app/src/rs3d/app/main.py`
- Create: `rs3d-app/src/rs3d/app/pages/__init__.py`
- Create: `rs3d-app/src/rs3d/app/pages/status.py`
- Create: `rs3d-app/src/rs3d/app/pages/live.py`
- Create: `rs3d-app/src/rs3d/app/pages/data.py`
- Create: `rs3d-app/src/rs3d/app/pages/guide.py`
- Create: `rs3d-app/src/rs3d/app/pages/settings.py`
- Create: `rs3d-app/src/rs3d/cli.py`
- Create: `rs3d-app/tests/app/sim_main.py`
- Test: `rs3d-app/tests/app/test_pages.py`

- [ ] **Step 1: Write the test app and the failing smoke tests** – `rs3d-app/tests/app/sim_main.py`:

```python
"""NiceGUI app used by the page smoke tests: real pages, fake device access."""

import os
from pathlib import Path

import numpy as np
from nicegui import ui
from obspy import Trace, UTCDateTime

from rs3d.app.main import build
from rs3d.app.state import AppState
from rs3d.core.devices import Passwords
from rs3d.core.live import LiveStream
from rs3d.core.models import Check, Device, Level
from rs3d.core.paths import AppPaths
from rs3d.core.status import ORDER


class MemoryKeyring:
    def __init__(self):
        self.data = {}

    def get_password(self, service, user):
        return self.data.get((service, user))

    def set_password(self, service, user, password):
        self.data[(service, user)] = password

    def delete_password(self, service, user):
        self.data.pop((service, user), None)


class FakeSource:
    def run(self, on_trace):
        start = UTCDateTime() - 30
        for ch in ("EHZ", "EHN", "EHE"):
            on_trace(Trace(np.sin(np.arange(3000) / 10.0) * 100,
                           header={"channel": ch, "starttime": start, "sampling_rate": 100.0}))
        raise ConnectionError("fake source ends")

    def close(self):
        pass


state = AppState(AppPaths(Path(os.environ["RS3D_DATA_DIR"])), passwords=Passwords(MemoryKeyring()))
state.save_device(Device(name="R77A7", host="169.254.221.62", station="R77A7"))
state.checks = lambda device: [Check(i, Level.OK, f"fake {i}", i) for i in ORDER]
_live = LiveStream(FakeSource, sleep=lambda s: None)
state.live = lambda device: (_live.start(), _live)[1]
build(state)
ui.run(reload=False)
```

`rs3d-app/tests/app/test_pages.py`:

```python
"""Smoke tests: every page renders with fake device access (NiceGUI user simulation, no browser)."""

import asyncio
from pathlib import Path

import pytest
from nicegui.testing.user_simulation import user_simulation

SIM_MAIN = Path(__file__).parent / "sim_main.py"


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("RS3D_DATA_DIR", str(tmp_path))


def run(scenario):
    async def go():
        async with user_simulation(main_file=SIM_MAIN) as user:
            await scenario(user)
    asyncio.run(go())


def test_status_page_lists_all_checks():
    async def scenario(user):
        await user.open("/status")
        await user.should_see("Laptop IP")
        await user.should_see("fake forwarding")
        await user.should_see("R77A7")
    run(scenario)


def test_live_page_controls():
    async def scenario(user):
        await user.open("/live")
        await user.should_see("Filter")
        await user.should_see("Save this segment")
    run(scenario)


def test_data_page_uses_query_range():
    async def scenario(user):
        await user.open("/data?start=1791831600&end=1791835200")  # 2026-10-12 20:00 -> 21:00 UTC
        await user.should_see("Download & preview")
        await user.should_see("1 h 00 m 00 s")
    run(scenario)


def test_settings_and_guide_pages():
    async def scenario(user):
        await user.open("/settings")
        await user.should_see("SSH user")
        await user.open("/guide")
        await user.should_see("RS3D Guide")
    run(scenario)


def test_index_redirects_to_status():
    async def scenario(user):
        await user.open("/")
        await user.should_see("Laptop IP")
    run(scenario)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/app/test_pages.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rs3d.app.main'`

- [ ] **Step 3: Implement the state and shared widgets** – `rs3d-app/src/rs3d/app/state.py`:

```python
"""Process-wide app state shared by all pages (one laptop, one user)."""

from __future__ import annotations

import tomllib

import tomli_w

from rs3d.core.devices import DeviceRegistry, Passwords
from rs3d.core.live import LiveStream
from rs3d.core.models import Check, Device
from rs3d.core.paths import AppPaths
from rs3d.core.seedlink import SeedLinkSource
from rs3d.core.shell import Shell
from rs3d.core.status import run_checks
from rs3d.core.store import Store

CHANNELS = ("EHZ", "EHN", "EHE")


class AppState:
    def __init__(self, paths: AppPaths, passwords: Passwords | None = None) -> None:
        self.paths = paths.ensure()
        self.registry = DeviceRegistry(paths.config)
        self.passwords = passwords or Passwords()
        self.store = Store(paths.sds)
        self._settings_path = paths.root / "settings.toml"
        settings = tomllib.loads(self._settings_path.read_text()) if self._settings_path.exists() else {}
        self.use_local_time: bool = bool(settings.get("use_local_time", False))
        devices = self.registry.load()
        self.current_host: str | None = settings.get("current_host") or (devices[0].host if devices else None)
        self._live: dict[str, LiveStream] = {}

    # ---------------------------------------------------------------- settings
    def save_settings(self) -> None:
        data = {"use_local_time": self.use_local_time}
        if self.current_host:
            data["current_host"] = self.current_host
        self._settings_path.write_text(tomli_w.dumps(data))

    def set_use_local_time(self, value: bool) -> None:
        self.use_local_time = value
        self.save_settings()

    # ---------------------------------------------------------------- devices
    def devices(self) -> list[Device]:
        return self.registry.load()

    def current(self) -> Device | None:
        devices = self.devices()
        return next((d for d in devices if d.host == self.current_host), devices[0] if devices else None)

    def select(self, host: str) -> None:
        self.current_host = host
        self.save_settings()

    def save_device(self, device: Device, password: str | None = None) -> None:
        self.registry.upsert(device)
        if password:
            self.passwords.set(device.host, password)
        self.select(device.host)

    def remove_device(self, host: str) -> None:
        self.stop_live(host)
        self.registry.remove(host)
        self.passwords.delete(host)
        if self.current_host == host:
            remaining = self.devices()
            self.current_host = remaining[0].host if remaining else None
            self.save_settings()

    # ---------------------------------------------------------------- connections
    def shell(self, device: Device) -> Shell:
        """SSH session; tries the SSH key/agent first, then the stored (or default) password."""
        return Shell(device, self.passwords.get_or_default(device.host), self.paths.known_hosts)

    def test_connection(self, device: Device) -> None:
        """Raises ShellError when SSH login fails."""
        with self.shell(device):
            pass

    def checks(self, device: Device) -> list[Check]:
        local_days = self.store.days(device.network, device.station, device.location, "EHZ")
        return run_checks(device, self.passwords.get_or_default(device.host), local_days=local_days,
                          shell_factory=lambda d, p: Shell(d, p, self.paths.known_hosts))

    def live(self, device: Device) -> LiveStream:
        stream = self._live.get(device.host)
        if stream is None:
            stream = LiveStream(lambda: SeedLinkSource(device.host, device.seedlink_port, device.network,
                                                       device.station, CHANNELS))
            self._live[device.host] = stream
        stream.start()
        return stream

    def stop_live(self, host: str) -> None:
        stream = self._live.pop(host, None)
        if stream:
            stream.stop()

    def stop_all(self) -> None:
        for host in list(self._live):
            self.stop_live(host)
```

`rs3d-app/src/rs3d/app/widgets.py`:

```python
"""Shared UI pieces: page frame with sidebar (layout A), (?) help icons, status icons."""

from __future__ import annotations

from nicegui import run, ui

from rs3d.app.state import AppState
from rs3d.app.strings import help_text, label
from rs3d.core.discovery import discover
from rs3d.core.models import Device, Level

NAV = (("status", "monitor_heart"), ("live", "show_chart"), ("data", "download"),
       ("guide", "menu_book"), ("settings", "settings"))
LEVEL_ICON = {Level.OK: ("check_circle", "positive"), Level.WARN: ("error", "warning"),
              Level.ERROR: ("cancel", "negative"), Level.SKIPPED: ("remove_circle_outline", "grey-5")}


def help_icon(help_id: str) -> None:
    """(?) icon: hover = short tooltip, click = detail panel."""
    short, detail = help_text(help_id)
    if not short:
        return
    with ui.dialog() as dialog, ui.card().classes("max-w-xl"):
        ui.markdown(detail)
        ui.button(label("action.close"), on_click=dialog.close).props("flat")
    icon = ui.icon("help_outline", size="xs").classes("cursor-pointer text-grey-6")
    icon.on("click", dialog.open)
    icon.tooltip(short)


def level_icon(level: Level) -> None:
    name, color = LEVEL_ICON[level]
    ui.icon(name, color=color, size="sm")


def frame(state: AppState, page: str) -> Device | None:
    """Header + left drawer with devices and pages. Returns the current device (or None)."""
    ui.colors(primary="#2f6fde")
    with ui.header().classes("items-center py-1 px-3 bg-primary"):
        ui.label(label("app")).classes("text-lg font-bold")
        ui.label("·").classes("opacity-60")
        ui.label(label(f"nav.{page}"))

    with ui.left_drawer(value=True, bordered=True).props("width=190").classes("p-2 gap-1"):
        ui.label(label("devices")).classes("text-xs uppercase text-grey-7")
        current = state.current()
        for d in state.devices():
            selected = current is not None and d.host == current.host
            ui.button(f"● {d.name}", on_click=lambda d=d: (state.select(d.host), ui.navigate.reload())) \
                .props(f"flat dense no-caps align=left {'color=primary' if selected else 'color=grey-8'}") \
                .classes("w-full")
        ui.button(label("find"), icon="search", on_click=lambda: _find_dialog(state)) \
            .props("flat dense no-caps align=left color=grey-8").classes("w-full")
        ui.separator().classes("my-2")
        for key, icon in NAV:
            ui.button(label(f"nav.{key}"), icon=icon, on_click=lambda key=key: ui.navigate.to(f"/{key}")) \
                .props(f"flat dense no-caps align=left {'color=primary' if key == page else 'color=grey-8'}") \
                .classes("w-full")
    return current


async def _find_dialog(state: AppState) -> None:
    with ui.dialog() as dialog, ui.card().classes("min-w-80"):
        ui.label(label("find")).classes("text-base font-bold")
        box = ui.column()
        with box:
            ui.spinner()
    dialog.open()
    found = await run.io_bound(discover)
    box.clear()
    with box:
        if not found:
            ui.label(label("no_device")).classes("text-grey-7")
        for f in found:
            with ui.row().classes("items-center gap-3"):
                ui.label(f"{f.info.network}.{f.info.station}").classes("font-mono")
                ui.label(f.host).classes("text-grey-7")

                def add(f=f) -> None:
                    state.save_device(Device(name=f.info.station, host=f.host, network=f.info.network,
                                             station=f.info.station, location=f.info.location))
                    dialog.close()
                    ui.navigate.to("/status")

                ui.button(label("action.add"), on_click=add).props("dense")
        ui.button(label("action.close"), on_click=dialog.close).props("flat")
```

- [ ] **Step 4: Implement the pages** – `rs3d-app/src/rs3d/app/pages/__init__.py`:

```python
"""One module per page; each exposes register(state)."""
```

`rs3d-app/src/rs3d/app/pages/status.py`:

```python
"""Status page: one row per check, refreshed every 30 s."""

from __future__ import annotations

import platform
import shlex
import time

from nicegui import run, ui

from rs3d.app.state import AppState
from rs3d.app.strings import label
from rs3d.app.widgets import frame, help_icon, level_icon
from rs3d.core import netcheck
from rs3d.core.models import Check

_NOT_WIRED = ("lo", "docker", "veth", "virbr", "br-", "tailscale", "wl", "wi-fi", "wlan", "loopback", "utun",
              "awdl", "llw", "bridge", "vmnet", "zt")


def wired_candidates() -> list[str]:
    return [i.name for i in netcheck.interfaces()
            if i.is_up and not i.name.lower().startswith(_NOT_WIRED)]


def register(state: AppState) -> None:
    @ui.page("/status")
    def status_page() -> None:
        device = frame(state, "status")
        if device is None:
            ui.label(label("no_device")).classes("text-grey-7")
            return
        with ui.row().classes("items-center gap-3"):
            ui.label(f"{device.name}").classes("text-lg font-bold")
            ui.label(device.host).classes("text-grey-7 font-mono")
            updated = ui.label("").classes("text-xs text-grey-6")
            ui.button(icon="refresh", on_click=lambda: refresh()).props("flat round dense") \
                .tooltip(label("action.refresh"))
        rows = ui.column().classes("gap-0 w-full max-w-2xl")
        with rows:
            ui.spinner()
        stamp = {"t": 0.0}

        def render(checks: list[Check]) -> None:
            rows.clear()
            with rows:
                for c in checks:
                    with ui.row().classes("items-center gap-2 w-full py-1 border-b border-grey-3"):
                        level_icon(c.level)
                        ui.label(label(f"check.{c.id}")).classes("w-36")
                        ui.label(c.value).classes("text-grey-8 font-mono text-sm grow")
                        help_icon(c.help_id or c.id)
                        if c.action == "set_ip":
                            ui.button(label("action.set_ip"), on_click=lambda: set_ip_dialog(refresh)) \
                                .props("dense unelevated")
                        elif c.action == "download":
                            ui.button(label("action.download"), on_click=lambda: ui.navigate.to("/data")) \
                                .props("dense flat")

        async def refresh() -> None:
            checks = await run.io_bound(state.checks, device)
            if checks is None:  # client went away
                return
            render(checks)
            stamp["t"] = time.monotonic()

        def tick_label() -> None:
            if stamp["t"]:
                updated.text = f"{int(time.monotonic() - stamp['t'])} s ago"

        ui.timer(0.1, refresh, once=True)
        ui.timer(30, refresh)
        ui.timer(1, tick_label)


def set_ip_dialog(after) -> None:
    system = platform.system()
    names = wired_candidates()
    with ui.dialog() as dialog, ui.card().classes("min-w-96"):
        ui.label(label("setip.title")).classes("text-base font-bold")
        choice = ui.select(names, value=names[0] if names else None, label=label("setip.interface")) \
            .classes("w-full")
        ui.label(label("setip.commands")).classes("text-xs text-grey-7")
        preview = ui.code("", language="bash").classes("w-full")

        async def show() -> None:
            if not choice.value:
                preview.content = ""
                return
            try:
                target = await run.io_bound(netcheck.resolve_target, system, choice.value)
                cmds = netcheck.set_ip_commands(system, choice.value, target)
                preview.content = "\n".join(shlex.join(c) for c in cmds)
            except Exception as exc:
                preview.content = f"# {exc}"

        async def apply() -> None:
            try:
                await run.io_bound(netcheck.set_ip, choice.value, system)
                ui.notify(label("setip.done"), type="positive")
                dialog.close()
                await after()
            except Exception as exc:
                ui.notify(str(exc), type="negative", multi_line=True)

        choice.on_value_change(show)
        with ui.row():
            ui.button(label("action.run"), on_click=apply).props("unelevated")
            ui.button(label("action.cancel"), on_click=dialog.close).props("flat")
    dialog.open()
    ui.timer(0.05, show, once=True)
```

`rs3d-app/src/rs3d/app/pages/live.py`:

```python
"""Live page: three channels in real time."""

from __future__ import annotations

from nicegui import ui

from rs3d.app.charts import set_live_data, waveform_options
from rs3d.app.state import CHANNELS, AppState
from rs3d.app.strings import label
from rs3d.app.widgets import frame, help_icon

WINDOWS = {30: "30 s", 60: "60 s", 300: "5 min"}
LIVE_FILTER = (1.0, 10.0)


def register(state: AppState) -> None:
    @ui.page("/live")
    def live_page() -> None:
        device = frame(state, "live")
        if device is None:
            ui.label(label("no_device")).classes("text-grey-7")
            return
        stream = state.live(device)
        view = {"paused": False}

        with ui.row().classes("items-center gap-4"):
            window = ui.toggle(WINDOWS, value=60).props("dense no-caps")
            with ui.row().classes("items-center gap-1"):
                flt = ui.switch(label("live.filter"), value=True)
                help_icon("live_filter")
            pause = ui.button(label("action.pause"), icon="pause").props("flat dense no-caps")
            ui.button(label("action.save_segment"), icon="content_cut", on_click=lambda: save_segment()) \
                .props("flat dense no-caps")
            status = ui.label("").classes("text-sm text-grey-7")

        chart = ui.echart(waveform_options(CHANNELS, use_utc=not state.use_local_time)) \
            .classes("w-full").style("height: 72vh")

        def toggle_pause() -> None:
            view["paused"] = not view["paused"]
            pause.text = label("action.resume") if view["paused"] else label("action.pause")
            pause.props(f"icon={'play_arrow' if view['paused'] else 'pause'}")

        pause.on_click(toggle_pause)

        def tick() -> None:
            state_key = stream.state
            if stream.state == "live" and stream.is_stale():
                state_key = "waiting"
            status.text = label(f"live.{state_key}")
            if view["paused"]:
                return
            end = stream.buffer.latest()
            if end is None:
                return
            seconds = window.value
            bandpass = LIVE_FILTER if flt.value else None
            snaps = {ch: stream.buffer.snapshot(ch, seconds, end, max_points=1500, bandpass=bandpass)
                     for ch in CHANNELS}
            set_live_data(chart.options, snaps, (end - seconds, end))
            chart.update()

        def save_segment() -> None:
            end = stream.buffer.latest()
            if end is None:
                return
            ui.navigate.to(f"/data?start={int(end - window.value)}&end={int(end) + 1}")

        ui.timer(0.25, tick)
```

`rs3d-app/src/rs3d/app/pages/data.py`:

```python
"""Data page: choose a station and time range, download from the Shake or import a file, preview, export."""

from __future__ import annotations

import tempfile
from pathlib import Path
from urllib.parse import urlencode

from nicegui import run, ui
from obspy import UTCDateTime

from rs3d.app import timeutil
from rs3d.app.charts import coverage_options, set_selection, set_stream_data, waveform_options
from rs3d.app.state import CHANNELS, AppState
from rs3d.app.strings import label
from rs3d.app.widgets import frame, help_icon
from rs3d.core import archive
from rs3d.core.codegen import generate
from rs3d.core.coverage import State, coverage
from rs3d.core.export import load_processed, write_csv, write_mseed, write_plot
from rs3d.core.models import Device, Selection
from rs3d.core.response import cache_path, cached_inventory, get_inventory

ZOOMS = ("week", "day", "hour")
MAX_IMPORT_BYTES = 2_000_000_000


def files_needed(remote: set, local_days_by_channel: dict, start: UTCDateTime, end: UTCDateTime,
                 channels: tuple[str, ...]) -> int:
    return sum(len(archive.days_to_fetch(remote, local_days_by_channel.get(ch, set()), start.date,
                                         (end - 1e-6).date)) for ch in channels)


def station_key(net: str, sta: str, loc: str) -> str:
    return f"{net}.{sta}.{loc}"


def station_choices(state: AppState, device: Device | None) -> list[str]:
    """Stations with data on this laptop, plus the current Shake (first)."""
    keys = [station_key(*s) for s in state.store.stations()]
    if device is not None and device.station:
        dev_key = station_key(device.network, device.station, device.location)
        if dev_key in keys:
            keys.remove(dev_key)
        keys.insert(0, dev_key)
    return keys


def default_range(state: AppState, net: str, sta: str, loc: str, channel: str) -> list[UTCDateTime]:
    """Last hour of the newest local data (imported files are usually not 'now')."""
    newest = max(state.store.days(net, sta, loc, channel))
    day_end = UTCDateTime(newest.year, newest.month, newest.day) + 86400
    segs = coverage(state.store, net, sta, loc, channel, day_end - 86400, day_end, set())
    end = max((s.end for s in segs if s.state is State.LOCAL), default=day_end)
    return [UTCDateTime(int(end.timestamp)) - 3600, UTCDateTime(int(end.timestamp))]


def register(state: AppState) -> None:
    @ui.page("/data")
    def data_page(start: str | None = None, end: str | None = None, station: str | None = None) -> None:
        device = frame(state, "data")
        choices = station_choices(state, device)

        async def on_import(e) -> None:
            target = Path(tempfile.mkdtemp()) / Path(e.file.name).name
            await e.file.save(target)
            try:
                written = await run.io_bound(state.store.import_file, target)
            except Exception as exc:
                ui.notify(f"{e.file.name}: {exc}", type="negative", multi_line=True)
                return
            if not written:
                ui.notify(f"{e.file.name}: {label('data.nothing')}", type="warning")
                return
            parts = written[0].name.split(".")
            key = station_key(parts[0], parts[1], parts[2])
            ui.notify(f"{label('data.imported')}: {key} ({len(written)})", type="positive")
            ui.navigate.to("/data?" + urlencode({"station": key}))

        with ui.row().classes("items-center gap-2"):
            picker = ui.select(choices, value=station if station in choices else (choices[0] if choices else None),
                               label=label("data.station")).props("dense").classes("w-56")
            uploader = ui.upload(auto_upload=True, on_upload=on_import, max_file_size=MAX_IMPORT_BYTES) \
                .props('accept=".mseed,.msd,.miniseed,.ms"').classes("hidden")
            ui.button(label("data.import"), icon="upload_file",
                      on_click=lambda: uploader.run_method("pickFiles")).props("flat dense no-caps")
            help_icon("import")
        if not choices:
            ui.label(label("data.empty")).classes("text-grey-7")
            return

        net, sta, loc = picker.value.split(".")
        is_device = device is not None and (device.network, device.station, device.location) == (net, sta, loc)
        channels = tuple(state.store.channels(net, sta, loc))
        if is_device:
            channels = tuple(dict.fromkeys(CHANNELS + channels))
        picker.on_value_change(lambda e: ui.navigate.to("/data?" + urlencode({"station": e.value})))

        if start and end:
            sel = [UTCDateTime(float(start)), UTCDateTime(float(end))]
        elif is_device or not channels:
            sel = list(timeutil.preset_range("last_hour", UTCDateTime(), state.use_local_time))
        else:
            sel = default_range(state, net, sta, loc, channels[0])
        if not channels:
            ui.label(label("data.nothing")).classes("text-grey-7")
            return
        ctx = {"zoom": "day", "view": timeutil.view_range("day", sel[1]), "remote": set(), "stream": None}

        # ------------------------------------------------------------ 1. time range
        with ui.row().classes("items-center gap-2"):
            start_in = ui.input(label("data.start")).props("dense").classes("w-48 font-mono")
            end_in = ui.input(label("data.end")).props("dense").classes("w-48 font-mono")
            with ui.button(icon="schedule").props("flat dense").tooltip(label("data.presets")):
                with ui.menu():
                    for p in timeutil.PRESETS:
                        ui.menu_item(label(f"preset.{p}"), on_click=lambda p=p: apply_preset(p))
            tz = ui.toggle({False: label("data.utc"), True: label("data.local")}, value=state.use_local_time) \
                .props("dense no-caps")
            help_icon("timezone")
            duration = ui.label("").classes("text-sm text-grey-7")

        with ui.row().classes("items-center gap-2 w-full"):
            ui.toggle({z: label(f"data.{z}") for z in ZOOMS}, value="day",
                      on_change=lambda e: set_zoom(e.value)).props("dense no-caps")
            ui.button(icon="chevron_left", on_click=lambda: move(-1)).props("flat dense round")
            view_label = ui.label("").classes("font-mono text-sm")
            ui.button(icon="chevron_right", on_click=lambda: move(1)).props("flat dense round")
            help_icon("coverage")
        bar = ui.echart(coverage_options(ctx["view"], [], tuple(sel), use_utc=not state.use_local_time)) \
            .classes("w-full").style("height: 90px")

        with ui.row().classes("items-center gap-2"):
            needed = ui.label("").classes("text-sm")
            help_icon("files_needed")

        # ------------------------------------------------------------ 2. processing
        with ui.row().classes("items-center gap-4"):
            ch_boxes = {ch: ui.checkbox(ch, value=True) for ch in channels}
            flt = ui.switch(label("data.filter"), value=False)
            fmin = ui.number(value=1.0, min=0.01, step=0.5, format="%.2f").props("dense").classes("w-20")
            fmax = ui.number(value=10.0, min=0.02, step=0.5, format="%.2f").props("dense").classes("w-20")
            ui.label("Hz")
            with ui.row().classes("items-center gap-1"):
                units = ui.toggle(["counts", "m/s"], value="counts").props("dense no-caps")
                help_icon("units")
            go = ui.button(label("action.download_preview" if is_device else "action.preview"),
                           icon="download" if is_device else "visibility").props("unelevated")

        # ------------------------------------------------------------ 3. preview / 4. export
        progress = ui.label("").classes("text-sm text-grey-7")
        status = {"text": ""}  # written by the worker thread, shown by a UI timer
        ui.timer(0.3, lambda: setattr(progress, "text", status["text"]))
        preview = ui.echart(waveform_options(channels, use_utc=not state.use_local_time)) \
            .classes("w-full").style("height: 48vh")
        with ui.row().classes("items-center gap-2"):
            ui.label(label("data.export")).classes("font-bold")
            export_buttons = [
                ui.button("miniSEED", on_click=lambda: export("mseed")).props("flat dense no-caps"),
                ui.button("CSV", on_click=lambda: export("csv")).props("flat dense no-caps"),
                ui.button("PNG", on_click=lambda: export("png")).props("flat dense no-caps"),
                ui.button("PDF", on_click=lambda: export("pdf")).props("flat dense no-caps"),
                ui.button("</> " + label("data.code"), on_click=lambda: show_code()).props("flat dense no-caps"),
            ]
            help_icon("code")
        for b in export_buttons:
            b.disable()

        # ------------------------------------------------------------ helpers
        def selection() -> Selection:
            chans = tuple(ch for ch, box in ch_boxes.items() if box.value) or channels
            band = (float(fmin.value), float(fmax.value)) if flt.value else None
            return Selection(net, sta, loc, sel[0], sel[1], channels=chans, filter=band, units=units.value)

        def write_fields() -> None:
            start_in.value = timeutil.to_text(sel[0], tz.value)
            end_in.value = timeutil.to_text(sel[1], tz.value)
            seconds = int(sel[1] - sel[0])
            duration.text = f"{seconds // 3600} h {seconds % 3600 // 60:02d} m {seconds % 60:02d} s"
            local = {ch: state.store.days(net, sta, loc, ch) for ch in channels}
            n = files_needed(ctx["remote"], local, sel[0], sel[1], selection().channels)
            needed.text = f"{label('data.files_needed')}: {n}"

        def redraw_bar() -> None:
            view = ctx["view"]
            view_label.text = f"{timeutil.to_text(view[0], tz.value)[:16]} → {timeutil.to_text(view[1], tz.value)[:16]}"
            segs = coverage(state.store, net, sta, loc, channels[0], view[0], view[1], ctx["remote"])
            bar.options.clear()
            bar.options.update(coverage_options(view, segs, tuple(sel), now=UTCDateTime(), use_utc=not tz.value))
            bar.update()

        def set_range(a: UTCDateTime, b: UTCDateTime) -> None:
            if b <= a:
                return
            sel[0], sel[1] = a, b
            if not (ctx["view"][0] <= a and b <= ctx["view"][1]):
                ctx["view"] = timeutil.view_range(ctx["zoom"], b)
                redraw_bar()
            else:
                set_selection(bar.options, (a, b))
                bar.update()
            write_fields()

        def apply_preset(name: str) -> None:
            a, b = timeutil.preset_range(name, UTCDateTime(), tz.value)
            if name == "last_7_days":
                ctx["zoom"] = "week"
            set_range(a, b)

        def on_field(_=None) -> None:
            try:
                a = timeutil.from_text(start_in.value, tz.value)
                b = timeutil.from_text(end_in.value, tz.value)
            except ValueError:
                ui.notify(label("data.bad_time"), type="warning")
                return
            set_range(a, b)

        def on_zoom(e) -> None:
            args = e.args or {}
            batch = args.get("batch") or [args]
            a_pct, b_pct = batch[0].get("start"), batch[0].get("end")
            if a_pct is None or b_pct is None:
                return
            a = timeutil.percent_to_time(ctx["view"], a_pct)
            b = timeutil.percent_to_time(ctx["view"], b_pct)
            if b > a:
                sel[0], sel[1] = a, b
                write_fields()

        def set_zoom(level: str) -> None:
            ctx["zoom"] = level
            ctx["view"] = timeutil.view_range(level, sel[1])
            redraw_bar()

        def move(direction: int) -> None:
            ctx["view"] = timeutil.view_range(ctx["zoom"],
                                              timeutil.shift_view(ctx["zoom"], ctx["view"][0], direction))
            redraw_bar()

        def on_tz(_=None) -> None:
            state.set_use_local_time(tz.value)
            write_fields()
            redraw_bar()
            preview.options["useUTC"] = not tz.value
            preview.update()

        start_in.on("keydown.enter", on_field)
        start_in.on("blur", on_field)
        end_in.on("keydown.enter", on_field)
        end_in.on("blur", on_field)
        tz.on_value_change(on_tz)
        bar.on("chart:datazoom", on_zoom)
        for box in ch_boxes.values():
            box.on_value_change(lambda _: write_fields())

        async def load_remote_days() -> None:
            def fetch() -> set:
                with state.shell(device) as sh:
                    return archive.list_remote_days(sh.sftp(), net, sta, loc, channels[0])
            try:
                ctx["remote"] = await run.io_bound(fetch) or set()
            except Exception:
                ctx["remote"] = set()
            write_fields()
            redraw_bar()

        async def download_and_preview() -> None:
            s = selection()
            go.disable()
            try:
                def work():
                    if is_device:
                        try:
                            with state.shell(device) as sh:
                                archive.sync(sh.sftp(), state.store, net, sta, loc, s.channels,
                                             s.start.date, (s.end - 1e-6).date,
                                             progress=lambda i, n, what: status.update(
                                                 text=f"{label('data.downloading')} {i}/{n}: {what}"))
                        except Exception as exc:  # offline: use what is already on the laptop
                            status["text"] = str(exc)
                    inv = None
                    if s.units == "m/s":
                        inv = cached_inventory(state.paths.response, net, sta) or \
                            get_inventory(state.paths.response, net, sta)
                    return load_processed(state.store, s, inv)

                st = await run.io_bound(work)
                if st is None:  # client went away
                    return
                ctx["stream"] = st
                set_stream_data(preview.options, st)
                preview.update()
                status["text"] = "" if len(st) else label("data.nothing")
                for b in export_buttons:
                    b.enable() if len(st) else b.disable()
                redraw_bar()
                write_fields()
            except Exception as exc:
                ui.notify(str(exc), type="negative", multi_line=True)
            finally:
                go.enable()

        go.on_click(download_and_preview)

        def base_name(s: Selection) -> str:
            return f"{s.network}.{s.station}_{s.start.strftime('%Y%m%dT%H%M%S')}_{s.end.strftime('%Y%m%dT%H%M%S')}"

        async def export(kind: str) -> None:
            st, s = ctx["stream"], selection()
            if st is None:
                return
            out = Path(tempfile.mkdtemp()) / f"{base_name(s)}.{kind}"
            writers = {"mseed": lambda: write_mseed(st, out), "csv": lambda: write_csv(st, out, s.channels),
                       "png": lambda: write_plot(st, out), "pdf": lambda: write_plot(st, out)}
            await run.io_bound(writers[kind])
            ui.download.file(out, out.name)

        def show_code() -> None:
            s = selection()
            inv_path = cache_path(state.paths.response, net, sta) if s.units == "m/s" else None
            code = generate(s, state.paths.sds, inv_path)
            with ui.dialog() as dialog, ui.card().classes("w-full max-w-3xl"):
                ui.code(code, language="python").classes("w-full")
                with ui.row():
                    ui.button(label("action.save_py"),
                              on_click=lambda: ui.download.content(code, f"{base_name(s)}.py")).props("flat")
                    ui.button(label("action.close"), on_click=dialog.close).props("flat")
            dialog.open()

        write_fields()
        redraw_bar()
        if is_device:
            ui.timer(0.1, load_remote_days, once=True)
```

`rs3d-app/src/rs3d/app/pages/guide.py`:

```python
"""Guide page: the bundled Markdown manual."""

from __future__ import annotations

from nicegui import ui

from rs3d.app.state import AppState
from rs3d.app.strings import guide_markdown
from rs3d.app.widgets import frame


def register(state: AppState) -> None:
    @ui.page("/guide")
    def guide_page() -> None:
        frame(state, "guide")
        ui.markdown(guide_markdown()).classes("max-w-3xl")
```

`rs3d-app/src/rs3d/app/pages/settings.py`:

```python
"""Settings page: per-device connection settings and app-wide options."""

from __future__ import annotations

from pathlib import Path

from nicegui import run, ui

from rs3d.app.state import AppState
from rs3d.app.strings import label
from rs3d.app.widgets import frame, help_icon
from rs3d.core.models import Device
from rs3d.core.shell import ShellError


def register(state: AppState) -> None:
    @ui.page("/settings")
    def settings_page() -> None:
        current = frame(state, "settings")
        ui.label(label("settings.device")).classes("text-base font-bold")
        with ui.card().classes("w-full max-w-xl"):
            name = ui.input(label("settings.name"), value=current.name if current else "").classes("w-full")
            host = ui.input(label("settings.host"), value=current.host if current else "").classes("w-full")
            port = ui.number(label("settings.port"), value=current.seedlink_port if current else 18000,
                             format="%d").classes("w-full")
            user = ui.input(label("settings.user"), value=current.ssh_user if current else "myshake") \
                .classes("w-full")
            password = ui.input(label("settings.password"), password=True, password_toggle_button=True) \
                .classes("w-full")
            key = ui.input(label("settings.key"),
                           value=str(current.key_path) if current and current.key_path else "").classes("w-full")

            def build() -> Device:
                base = current or Device(name="", host="")
                return Device(name=name.value.strip() or host.value.strip(), host=host.value.strip(),
                              seedlink_port=int(port.value or 18000), ssh_user=user.value.strip() or "myshake",
                              key_path=Path(key.value.strip()) if key.value.strip() else None,
                              network=base.network, station=base.station or name.value.strip(),
                              location=base.location)

            async def test() -> None:
                device = build()
                if password.value:
                    state.passwords.set(device.host, password.value)
                try:
                    await run.io_bound(state.test_connection, device)
                    ui.notify(label("settings.ok"), type="positive")
                except ShellError as exc:
                    ui.notify(str(exc), type="negative")

            def save() -> None:
                if not host.value.strip():
                    return
                state.save_device(build(), password.value or None)
                ui.notify(label("settings.saved"), type="positive")
                ui.navigate.reload()

            def remove() -> None:
                if current:
                    state.remove_device(current.host)
                    ui.navigate.reload()

            with ui.row():
                ui.button(label("action.save"), on_click=save).props("unelevated")
                ui.button(label("action.test"), on_click=test).props("flat")
                if current:
                    ui.button(label("action.remove"), on_click=remove).props("flat color=negative")
                ui.button(label("settings.new"), on_click=lambda: (setattr(state, "current_host", None),
                                                                   ui.navigate.reload())).props("flat")

        ui.label(label("settings.app")).classes("text-base font-bold mt-4")
        with ui.card().classes("w-full max-w-xl"):
            with ui.row().classes("items-center gap-2"):
                ui.label(label("settings.timezone"))
                ui.toggle({False: label("data.utc"), True: label("data.local")}, value=state.use_local_time,
                          on_change=lambda e: state.set_use_local_time(e.value)).props("dense no-caps")
                help_icon("timezone")
            with ui.row().classes("items-center gap-2"):
                ui.label(label("settings.data_dir"))
                ui.label(str(state.paths.root)).classes("font-mono text-sm text-grey-8")
```

- [ ] **Step 5: Implement the entry points** – `rs3d-app/src/rs3d/app/main.py`:

```python
"""Build all pages and start the NiceGUI server."""

from __future__ import annotations

import socket

from nicegui import app, ui

from rs3d.app.pages import data, guide, live, settings, status
from rs3d.app.state import AppState
from rs3d.core.paths import AppPaths


def build(state: AppState) -> None:
    for page in (status, live, data, guide, settings):
        page.register(state)

    @ui.page("/")
    def index() -> None:
        ui.navigate.to("/status" if state.devices() else "/settings")

    app.on_shutdown(state.stop_all)


def free_port(preferred: int = 8765) -> int:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def run(port: int | None = None, show: bool = True, native: bool = False) -> None:
    state = AppState(AppPaths.default())
    build(state)
    ui.run(title="RS3D", host="127.0.0.1", port=port or free_port(), show=show, native=native,
           reload=False, favicon="🌍", show_welcome_message=True)
```

`rs3d-app/src/rs3d/cli.py`:

```python
"""`rs3d-app` command."""

from __future__ import annotations

import argparse


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="rs3d-app", description="Raspberry Shake 3D status, live view and data export")
    parser.add_argument("--port", type=int, default=None, help="web port (default 8765, or a free one)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    args = parser.parse_args(argv)

    from rs3d.app.main import run

    run(port=args.port, show=not args.no_browser)


if __name__ in {"__main__", "__mp_main__"}:
    main()
```

- [ ] **Step 6: Run to verify they pass**

Run: `uv sync && uv run pytest tests/app/test_pages.py -v`
Expected: 5 passed

- [ ] **Step 7: Commit**

```bash
git add rs3d-app/src/rs3d/app rs3d-app/src/rs3d/cli.py rs3d-app/tests/app/sim_main.py rs3d-app/tests/app/test_pages.py
git commit -m "feat(rs3d-app): NiceGUI pages, sidebar layout and rs3d-app command"
```

---

### Task 6: Full suite and offline check with a real file

- [ ] **Step 1: Run everything**

Run: `uv run pytest -q`
Expected: `116 passed, 5 deselected`

- [ ] **Step 2: Offline check** (no Shake needed). Start the app with a throw-away data folder:

```bash
RS3D_DATA_DIR=/tmp/rs3d-check PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring uv run rs3d-app --no-browser
```

Open http://127.0.0.1:8765/data, press **Import miniSEED** and choose `../rsudp_out/data/fdsnws.mseed` (AM.RF7B3, EHZ, 2026-10-11 18:07 → 2026-10-12 17:37 UTC). Expected (measured on the reference laptop): import ≈ 4 s, the page reopens on station `AM.RF7B3.00` with the last hour selected (16:37:39 → 17:37:39 UTC), coverage bar green until 17:37 then red; **Preview** ≈ 4 s; axis labels 16:40 … 17:35 in UTC mode; exports: miniSEED ≈ 0.5 MB, CSV ≈ 13 MB, PNG, PDF; **Code** opens the ObsPy snippet. Stop the app with Ctrl+C.

---

## Pending: needs a Shake on the cable (do later)

These parts are implemented and unit-tested with fakes, but have not yet been exercised through the UI with a real Shake. When the Shake is connected again, check each one and fix what differs:

1. **Live page with real data**: waveforms move, 30 s / 60 s / 5 min, filter on/off, Pause, Save this segment → Data page with the same range; unplug the cable → "reconnecting…" then recovery.
2. **Status page with a real Shake**: all 11 checks green/amber as on the command line (`pytest -m device` already passes for the core).
3. **Find Shake…** dialog finds R77A7 and adds it.
4. **Settings → Test connection** with the right and with a wrong password (error kind shown).
5. **Data page for the Shake**: coverage shows grey days on the Shake, "Files to download" count, **Download & preview** copies day files (progress text), then exports.
6. **m/s units** with the response downloaded from the Raspberry Shake FDSN service (needs Internet on the laptop once).
7. **Set IP** on Linux (polkit prompt), and later on Windows and macOS.
8. Spec 7: unplug during a download → no `.part` file left, next download restarts that file.
