"""DetailPanel behaviour that needs a running page: stale context, failed loads, clipboard save."""

import asyncio
from pathlib import Path

import numpy as np
import pytest
from nicegui.testing.user_simulation import user_simulation
from obspy import Trace, UTCDateTime

from rs3d.app.detail import DetailContext, detail_title
from rs3d.core.store import Store
from tests.app.registry import REG

SIM = Path(__file__).parent / "sim_detail.py"
T = UTCDateTime("2026-10-12T00:05:00")


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("RS3D_DATA_DIR", str(tmp_path))
    tr = Trace(np.random.default_rng(0).integers(-500, 500, 60000).astype("int32"),
               header={"network": "AM", "station": "R77A7", "location": "00", "channel": "EHZ",
                       "sampling_rate": 100.0, "starttime": UTCDateTime("2026-10-12T00:00:00")})
    path = tmp_path / "10min.mseed"
    tr.write(str(path), format="MSEED")
    Store(tmp_path / "sds").import_file(path)
    REG.clear()


def run(scenario):
    async def go():
        async with user_simulation(main_file=SIM) as user:
            await user.open("/t")
            with REG["client"].content:
                await scenario()
    asyncio.run(go())


def ctx(units="counts", band=None):
    return DetailContext("AM", "R77A7", "00", "EHZ", units, band, True)


def test_title_states_units_and_filter():
    a, b = UTCDateTime("2026-10-12T00:00:00"), UTCDateTime("2026-10-12T00:02:00")
    assert detail_title(ctx(), (a, b)).endswith("counts")
    assert detail_title(ctx("m/s", (1.0, 10.0)), (a, b)).endswith("m/s  band-pass 1–10 Hz")


def test_loaded_context_is_kept_until_the_panel_reloads():
    async def scenario():
        REG["ctx"]["ctx"] = ctx()
        panel = REG["panel"]
        await panel.open(T)
        REG["ctx"]["ctx"] = ctx(band=(1.0, 10.0))  # the user turns the band-pass on
        assert panel.loaded.ctx.band is None       # what is on screen was loaded without it
        await panel.reload()
        assert panel.loaded.ctx.band == (1.0, 10.0)
    run(scenario)


def test_failed_zoom_keeps_window_and_data_in_step(monkeypatch):
    import rs3d.app.detail as detail

    def no_response(*a, **k):
        raise RuntimeError("no instrument response")

    monkeypatch.setattr(detail, "inventory_for", no_response)

    async def scenario():
        REG["ctx"]["ctx"] = ctx()
        panel = REG["panel"]
        await panel.open(T)
        before = panel.window
        REG["ctx"]["ctx"] = ctx("m/s")
        await panel.zoom(2.0)                      # load fails: window and data must stay as they were
        assert panel.window == before
        assert panel.loaded.ctx.units == "counts"
    run(scenario)


def test_saving_an_empty_window_does_not_raise():
    async def scenario():
        REG["ctx"]["ctx"] = ctx()
        panel = REG["panel"]
        await panel.open(UTCDateTime("2026-10-13T00:00:00"))  # no data on that day
        assert await panel.save_clipboard() is None
    run(scenario)
