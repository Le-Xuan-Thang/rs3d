"""Run with a Shake on the cable: RS3D_HOST=169.254.221.62 uv run pytest -m device -v

Uses the laptop's SSH key or agent (no password stored in tests).
"""

import os
import time
from datetime import date, timedelta

import pytest

from rs3d.core import archive
from rs3d.core.discovery import discover
from rs3d.core.live import LiveStream
from rs3d.core.models import Device, Level
from rs3d.core.seedlink import SeedLinkSource, probe
from rs3d.core.shell import Shell
from rs3d.core.status import run_checks
from rs3d.core.store import Store

pytestmark = pytest.mark.device
HOST = os.environ.get("RS3D_HOST", "169.254.221.62")


@pytest.fixture(scope="module")
def info():
    return probe(HOST)


@pytest.fixture
def device(info):
    return Device(name=info.station, host=HOST, station=info.station, network=info.network,
                  location=info.location)


def test_probe(info):
    assert {"EHZ", "EHN", "EHE"} <= set(info.channels)


def test_discover_finds_it(info):
    assert any(f.info.station == info.station for f in discover())


def test_status_has_no_errors(device, tmp_path):
    results = run_checks(device, None, shell_factory=lambda d, p: Shell(d, p, tmp_path / "kh"))
    assert [c.id for c in results if c.level is Level.ERROR] == []


def test_archive_sync_today(device, tmp_path):
    store = Store(tmp_path / "sds")
    with Shell(device, None, tmp_path / "kh") as sh:
        written = archive.sync(sh.sftp(), store, device.network, device.station, device.location,
                               ("EHZ",), date.today() - timedelta(days=1), date.today())
    assert written


def test_live_receives_data(device):
    live = LiveStream(lambda: SeedLinkSource(HOST, 18000, device.network, device.station, ("EHZ",)))
    live.start()
    try:
        deadline = time.monotonic() + 20
        while live.is_stale() and time.monotonic() < deadline:
            time.sleep(0.5)
        assert not live.is_stale()
    finally:
        live.stop()
