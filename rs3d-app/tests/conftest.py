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
