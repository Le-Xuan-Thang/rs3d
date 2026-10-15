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
        await user.should_see("Spectrogram")
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
