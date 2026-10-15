"""Run with a Shake on the cable: RS3D_HOST=169.254.221.62 uv run pytest -m device tests/device/test_clock.py -v

The second test changes the Shake's clock on purpose, so it only runs when RS3D_TEST_BREAK_CLOCK=1 is set.
It restores the clock from the laptop at the end.
"""

import os
import time

import pytest

from rs3d.core.clock import T, measure_offset, set_from_laptop, sync_now
from rs3d.core.models import Device
from rs3d.core.shell import Shell

pytestmark = pytest.mark.device
HOST = os.environ.get("RS3D_HOST", "169.254.221.62")


@pytest.fixture
def shell(tmp_path):
    with Shell(Device(name="shake", host=HOST), None, tmp_path / "known_hosts") as sh:
        yield sh


def test_offset_is_small_on_a_synced_shake(shell):
    assert abs(measure_offset(shell)) < 5 * T


@pytest.mark.skipif(os.environ.get("RS3D_TEST_BREAK_CLOCK") != "1",
                    reason="set RS3D_TEST_BREAK_CLOCK=1 to change the Shake's clock on purpose")
def test_sync_now_recovers_a_wrong_clock(shell):
    shell.run(f"sudo -n date -u -s @{int(time.time()) - 3600}")
    try:
        assert abs(measure_offset(shell)) > 3000
        res = sync_now(shell)
        assert res.ok, res.message
    finally:
        if abs(measure_offset(shell)) > T:
            set_from_laptop(shell)
