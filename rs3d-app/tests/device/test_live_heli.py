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
