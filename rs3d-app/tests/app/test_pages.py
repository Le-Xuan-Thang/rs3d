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
        await user.should_see("Hz")
    run(scenario)


def test_data_page_uses_query_range():
    async def scenario(user):
        await user.open("/data?start=1791831600&end=1791835200")  # 2026-10-12 20:00 -> 21:00 UTC
        await user.should_see("Download & preview")
        await user.should_see("1 h 00 m 00 s")
        await user.should_see("Spectrogram")
        await user.should_see("Noise spectrum")
        await user.should_see("Data health")
        await user.should_see("Choose a time range")
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


def test_data_page_remembers_band_pass_choice(tmp_path):
    import tomllib
    from nicegui import ui

    async def scenario(user):
        await user.open("/data?start=1791831600&end=1791835200")
        user.find(kind=ui.switch).click()
        saved = tomllib.loads((tmp_path / "settings.toml").read_text())
        assert saved["data_prefs"]["filter"] is True
        await user.open("/data?start=1791831600&end=1791835200")
        assert user.find(kind=ui.switch).elements.pop().value is True
    run(scenario)


def _write_day(tmp_path):
    """Ten minutes of EHZ on 2026-10-12 in the app's store."""
    import numpy as np
    from obspy import Trace, UTCDateTime
    from rs3d.core.store import Store
    tr = Trace(np.random.default_rng(0).integers(-500, 500, 60000).astype("int32"),
               header={"network": "AM", "station": "R77A7", "location": "00", "channel": "EHZ",
                       "sampling_rate": 100.0, "starttime": UTCDateTime("2026-10-12T00:00:00")})
    path = tmp_path / "10min.mseed"
    tr.write(str(path), format="MSEED")
    Store(tmp_path / "sds").import_file(path)


def test_helicorder_page_is_in_the_nav_and_shows_empty_message():
    async def scenario(user):
        await user.open("/helicorder")
        await user.should_see("Helicorder")
        await user.should_see("No data yet")
    run(scenario)


def test_helicorder_page_shows_requested_day_and_arrows_move_it(tmp_path):
    _write_day(tmp_path)

    async def scenario(user):
        await user.open("/helicorder?day=2026-10-12")
        await user.should_see("2026-10-12")
        user.find(marker="day-next").click()
        await user.should_see("2026-10-13")
        user.find(marker="day-prev").click()
        await user.should_see("2026-10-12")
    run(scenario)


def test_frequencies_page_without_data_says_so():
    async def scenario(user):
        await user.open("/frequencies")
        await user.should_see("No data in this range")
    run(scenario)


def test_frequencies_page_analyses_the_requested_range(tmp_path):
    _write_day(tmp_path)

    async def scenario(user):
        await user.open("/frequencies?start=1791763200&end=1791763800")  # 2026-10-12 00:00-00:10 UTC
        await user.should_see("Find frequencies")
        user.find(marker="freq-find").click()
        await user.should_see("resolution", retries=100)
    run(scenario)


def test_frequencies_page_shows_the_chosen_data_before_analysis(tmp_path):
    _write_day(tmp_path)

    async def scenario(user):
        await user.open("/frequencies?start=1791763200&end=1791763800")
        await user.should_see("Frequency versus time", retries=100)
        await user.should_see("Find frequencies")
    run(scenario)
