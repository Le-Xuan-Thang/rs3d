"""The real RS3D app, wired to a fake Shake, for the User's Guide screenshots.

    RS3D_DATA_DIR=<dir> python screenshot_app.py <port>

* the device "DEMO1" has realistic (fake) Status checks; /_mode/good and /_mode/bad switch them,
* the Live page replays the demo earthquake as if it were arriving now,
* the data folder is expected to already hold the demo day (make_screenshots.py prepares it),
* SFTP finds nothing on the "Shake", so Download & preview just uses the local files.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np
from nicegui import app, ui
from obspy import Trace, UTCDateTime

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_data as dd  # noqa: E402

from rs3d.app.main import build  # noqa: E402
from rs3d.app.state import AppState  # noqa: E402
from rs3d.core.devices import Passwords  # noqa: E402
from rs3d.core.live import LiveStream  # noqa: E402
from rs3d.core.models import Check, Device, Level  # noqa: E402
from rs3d.core.paths import AppPaths  # noqa: E402


class MemoryKeyring:
    def __init__(self):
        self.data = {}

    def get_password(self, service, user):
        return self.data.get((service, user))

    def set_password(self, service, user, password):
        self.data[(service, user)] = password

    def delete_password(self, service, user):
        self.data.pop((service, user), None)


GOOD = [
    Check("laptop_ip", Level.OK, "enp2s0 169.254.8.11", "laptop_ip"),
    Check("seedlink", Level.OK, "169.254.221.62:18000", "seedlink"),
    Check("channels", Level.OK, "EHZ EHN EHE", "channels"),
    Check("ssh", Level.OK, "myshake", "ssh"),
    Check("clock", Level.OK, "±0.84 ms via 162.159.200.1", "clock"),
    Check("internet", Level.OK, "yes", "internet"),
    Check("wifi", Level.OK, "192.168.1.57", "wifi"),
    Check("storage", Level.OK, "21.4 GB free (73%)", "storage"),
    Check("archive", Level.WARN, "2026-10-09 → 2026-10-15 · keeps 7 days · 1 day(s) about to be deleted",
          "archive.atrisk", action="download"),
    Check("forwarding", Level.OK, "OFF", "forwarding"),
    Check("password", Level.WARN, "default", "password"),
]
BAD = [Check("laptop_ip", Level.ERROR, "no 169.254.x.x address on a wired port", "laptop_ip", action="set_ip")] + \
      [Check(i, Level.SKIPPED, "", i) for i in ("seedlink", "channels", "ssh", "clock", "internet", "wifi",
                                                  "storage", "archive", "forwarding", "password")]
MODE = {"checks": GOOD}


# ten minutes around the local earthquake, read once at start-up from the demo file made by make_screenshots.py
from obspy import read  # noqa: E402

REPLAY = dd.cut(read(os.environ["DEMO_MSEED"]), UTCDateTime("2026-10-15T03:11:00"),
                UTCDateTime("2026-10-15T03:21:00"))


class ReplaySource:
    """Plays 03:11:55 of the demo day (the local earthquake starts 25 s later) as if it were happening now."""

    def __init__(self):
        self._stop = False
        self._st = REPLAY

    def run(self, on_trace):
        start = UTCDateTime("2026-10-15T03:11:55")
        shift = UTCDateTime() - (start + 120)
        k = 0
        t_wall = time.monotonic()
        while not self._stop:
            a = start + k
            for ch in dd.CHANNELS:
                piece = self._st.select(channel=ch).slice(a, a + 1 - 1e-6)
                if len(piece):
                    tr = piece[0].copy()
                    tr.stats.starttime = tr.stats.starttime + shift
                    on_trace(tr)
            k += 1
            if k > 120:  # after the backlog, play in real time
                time.sleep(max(0.0, t_wall + (k - 120) - time.monotonic()))
            if k > 560:
                raise ConnectionError("replay finished")

    def close(self):
        self._stop = True


class FakeSftp:
    def listdir(self, path):
        raise OSError("no archive on the fake Shake")

    def get(self, remote, local):
        raise OSError("no archive on the fake Shake")


class FakeShell:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def sftp(self):
        return FakeSftp()


state = AppState(AppPaths(Path(os.environ["RS3D_DATA_DIR"])), passwords=Passwords(MemoryKeyring()))
state.save_device(Device(name="DEMO1", host="169.254.221.62", station="DEMO1"))
state.checks = lambda device: MODE["checks"]
state.shell = lambda device: FakeShell()
_live = LiveStream(ReplaySource, sleep=lambda s: time.sleep(0.5))
state.live = lambda device: (_live.start(), _live)[1]
build(state)


@app.get("/_mode/{name}")
def set_mode(name: str):
    MODE["checks"] = BAD if name == "bad" else GOOD
    return {"mode": name}


ui.run(title="RS3D", host="127.0.0.1", port=int(sys.argv[1]), show=False, reload=False, show_welcome_message=False)
