"""Real-browser test: import a miniSEED file, preview it, check that every chart paints.

Needs Google Chrome (driven by Playwright). Run with:  uv run pytest -m e2e
"""

import os
import socket
import subprocess
import sys
import time
import urllib.request

import numpy as np
import pytest
from obspy import Stream, Trace, UTCDateTime

pytestmark = pytest.mark.e2e
playwright_sync = pytest.importorskip("playwright.sync_api")

START = UTCDateTime("2026-10-12T00:00:00")
PAINTED = """canvas => {
  const d = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
  let n = 0;
  for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++;
  return n;
}"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def mseed(tmp_path):
    """5 minutes, 3 channels, 100 Hz: a 5 Hz sine plus noise, with a 20 s hole in EHZ."""
    rng = np.random.default_rng(1)
    t = np.arange(0, 300, 0.01)
    st = Stream()
    for ch in ("EHZ", "EHN", "EHE"):
        data = (1000 * np.sin(2 * np.pi * 5 * t) + rng.normal(0, 100, len(t))).astype(np.int32)
        header = {"network": "AM", "station": "R77A7", "location": "00", "channel": ch,
                  "sampling_rate": 100.0}
        if ch == "EHZ":
            st += Trace(data[:10000], header={**header, "starttime": START})
            st += Trace(data[12000:], header={**header, "starttime": START + 120})
        else:
            st += Trace(data, header={**header, "starttime": START})
    path = tmp_path / "AM.R77A7.mseed"
    st.write(str(path), format="MSEED")
    return path


@pytest.fixture
def server(tmp_path):
    port = free_port()
    # NiceGUI switches to its own test-harness mode when it sees PYTEST_CURRENT_TEST
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    env["RS3D_DATA_DIR"] = str(tmp_path / "data")
    proc = subprocess.Popen([sys.executable, "-m", "rs3d.cli", "--no-browser", "--port", str(port)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(url, timeout=1)
                break
            except OSError:
                time.sleep(0.2)
        else:
            pytest.fail("rs3d-app did not start")
        yield url
    finally:
        proc.terminate()
        proc.wait(10)


def test_import_preview_paints_all_charts(server, mseed):
    with playwright_sync.sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(server + "/data")
        page.locator("input[type=file]").set_input_files(str(mseed))
        page.get_by_text("Preview", exact=True).wait_for(timeout=20000)
        page.get_by_text("Preview", exact=True).click()
        page.get_by_text("complete").wait_for(timeout=30000)
        assert "no gaps" not in page.get_by_text("complete").inner_text()  # EHZ has a hole
        page.wait_for_timeout(1000)
        canvases = page.locator(".nicegui-echart canvas")
        painted = [canvases.nth(i).evaluate(PAINTED) for i in range(canvases.count())]
        y = {name: page.get_by_text(name, exact=True).bounding_box()["y"]
             for name in ("Data health", "Spectrogram", "Noise spectrum")}
        spectrogram_chart_y = canvases.nth(2).bounding_box()["y"]
        browser.close()
    # each heading sits directly above its own chart
    assert y["Data health"] < y["Spectrogram"] < spectrogram_chart_y < y["Noise spectrum"], (y, spectrogram_chart_y)
    # coverage bar, waveforms, spectrogram, noise spectrum
    assert len(painted) >= 4 and all(n > 500 for n in painted), painted
