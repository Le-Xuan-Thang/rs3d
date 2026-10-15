"""NiceGUI app used by the page smoke tests: real pages, fake device access."""

import os
import time
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
# the fake source fails at once; without a pause the reconnect loop would spin and starve other tests
_live = LiveStream(FakeSource, sleep=lambda s: time.sleep(0.2))
state.live = lambda device: (_live.start(), _live)[1]
build(state)
ui.run(reload=False)
