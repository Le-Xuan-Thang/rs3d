"""Real-browser test: helicorder -> click a row -> detail view -> spectrogram -> clipboard -> PNG download.

Run with:  uv run pytest -m e2e
"""

import numpy as np
import pytest
from matplotlib import image
from obspy import Trace, UTCDateTime

from tests.e2e.test_data_flow import PAINTED, playwright_sync, server  # noqa: F401  (fixture re-export)

pytestmark = pytest.mark.e2e


@pytest.fixture
def three_hours(tmp_path):
    """3 h of EHZ at 100 Hz: noise plus a 5 Hz burst at minute 70, starting 2026-10-12 00:00 UTC."""
    rng = np.random.default_rng(2)
    n = 3 * 3600 * 100
    data = rng.normal(0, 100, n)
    data[70 * 6000:70 * 6000 + 3000] += 3000 * np.sin(2 * np.pi * 5 * np.arange(3000) / 100)
    tr = Trace(data.astype("int32"), header={"network": "AM", "station": "R77A7", "location": "00",
                                           "channel": "EHZ", "sampling_rate": 100.0,
                                           "starttime": UTCDateTime("2026-10-12T00:00:00")})
    path = tmp_path / "AM.R77A7.mseed"
    tr.write(str(path), format="MSEED")
    return path


def test_click_a_row_and_save_the_clipboard(server, three_hours, tmp_path):  # noqa: F811
    with playwright_sync.sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000}, accept_downloads=True)
        page.goto(server + "/data")
        page.locator("input[type=file]").set_input_files(str(three_hours))
        page.get_by_text("Preview", exact=True).wait_for(timeout=30000)
        page.goto(server + "/helicorder?station=AM.R77A7.00&day=2026-10-12")
        # the detail panel's (hidden) chart comes first in the page, the helicorder chart last
        page.wait_for_function(
            '[...document.querySelectorAll(".nicegui-echart canvas")].some(c => c.height > 600)', timeout=30000)
        page.wait_for_timeout(1500)
        box = page.locator(".nicegui-echart").last.bounding_box()
        # grid: left 56, right 56, top 8; row 2 (01:00-01:30), x = 10 min of 30
        x = box["x"] + 56 + (box["width"] - 112) * (10 / 30)
        y = box["y"] + 8 + 14 * (2 + 0.5)
        page.mouse.click(x, y)
        page.get_by_text("Spectrogram", exact=True).wait_for(timeout=15000)
        title = page.locator(".font-mono").filter(has_text="AM.R77A7.00.EHZ").first.inner_text()
        assert "2026-10-12 01:10:" in title or "2026-10-12 01:09:" in title, title  # window centred on 01:10
        page.get_by_text("Spectrogram", exact=True).click()
        page.wait_for_timeout(1500)
        # each ECharts chart draws into several stacked canvases (one is the empty hover layer):
        # a chart counts as painted when at least one of its canvases has pixels
        charts = page.locator(".nicegui-echart")
        painted = []
        for i in range(charts.count()):
            if charts.nth(i).is_visible():
                layers = charts.nth(i).locator("canvas")
                painted.append(max(layers.nth(j).evaluate(PAINTED) for j in range(layers.count())))
        assert len(painted) == 2 and all(n > 500 for n in painted), painted  # detail chart + helicorder
        # turning the band-pass on while the detail is open reloads it, and the title says so
        page.get_by_text("Band-pass", exact=True).first.click()
        page.locator(".font-mono").filter(has_text="band-pass 1–10 Hz").first.wait_for(timeout=15000)
        page.locator("[data-testid=clipboard]").click()
        with page.expect_download(timeout=30000) as dl:
            page.locator("[data-testid=camera]").click()
        out = tmp_path / "clip.png"
        dl.value.save_as(str(out))
        browser.close()
    img = image.imread(out)
    assert img.shape[0] > 500 and (img[..., :3] < 0.9).mean() > 0.02


# the y range the first (detail) chart is showing, and the range of the data it plots
Y_VIEW = """() => {
  const el = document.querySelector('.nicegui-echart');
  const chart = getElement(el.id.slice(1)).chart;
  const [lo, hi] = chart.getModel().getComponent('yAxis', 0).axis.scale.getExtent();
  const v = chart.getOption().series[0].data.map(p => p[1]).filter(x => x !== null);
  return {lo, hi, data_lo: Math.min(...v), data_hi: Math.max(...v)};
}"""


def _window_seconds(title: str) -> float:
    import re
    from datetime import datetime
    a, b = re.findall(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", title)
    fmt = "%Y-%m-%d %H:%M:%S"
    return (datetime.strptime(b, fmt) - datetime.strptime(a, fmt)).total_seconds()


def test_drag_a_rectangle_to_zoom_the_detail_view(server, three_hours):  # noqa: F811
    with playwright_sync.sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.goto(server + "/data")
        page.locator("input[type=file]").set_input_files(str(three_hours))
        page.get_by_text("Preview", exact=True).wait_for(timeout=30000)
        page.goto(server + "/helicorder?station=AM.R77A7.00&day=2026-10-12")
        page.wait_for_function(
            '[...document.querySelectorAll(".nicegui-echart canvas")].some(c => c.height > 600)', timeout=30000)
        page.wait_for_timeout(1500)
        box = page.locator(".nicegui-echart").last.bounding_box()
        page.mouse.click(box["x"] + 56 + (box["width"] - 112) * (10 / 30), box["y"] + 8 + 14 * 2.5)
        title_loc = page.locator(".font-mono").filter(has_text="AM.R77A7.00.EHZ").first
        title_loc.wait_for(timeout=15000)
        assert _window_seconds(title_loc.inner_text()) == 120.0
        # the brush must not draw its own button row on the first render
        assert page.evaluate("() => getElement(document.querySelector('.nicegui-echart').id.slice(1))"
                             ".chart.getOption().toolbox[0].show") is False
        page.locator("[data-testid=box-zoom]").click()
        chart = page.locator(".nicegui-echart").first.bounding_box()
        # drag from 30% to 50% of the width and 30% to 70% of the height of the detail chart
        page.mouse.move(chart["x"] + chart["width"] * 0.3, chart["y"] + chart["height"] * 0.3)
        page.mouse.down()
        page.mouse.move(chart["x"] + chart["width"] * 0.5, chart["y"] + chart["height"] * 0.7, steps=10)
        page.mouse.up()
        page.wait_for_function(
            "() => { const t = [...document.querySelectorAll('.font-mono')].find(e => e.textContent.includes('AM.R77A7.00.EHZ'));"
            " const m = t.textContent.match(/\\d{2}:\\d{2}:\\d{2}/g); return m && m[0] !== m[1]; }")
        page.wait_for_timeout(1500)
        span = _window_seconds(title_loc.inner_text())
        zoomed = page.evaluate(Y_VIEW)
        # Fit rescales the amplitude to the data in view and keeps the zoomed time width
        page.locator("[data-testid=fit]").click()
        page.wait_for_timeout(1500)
        fitted = page.evaluate(Y_VIEW)
        span_after_fit = _window_seconds(title_loc.inner_text())
        browser.close()
    assert 5 <= span < 60, span  # about a fifth of the 120 s window (clamped to at least 5 s)
    assert zoomed["lo"] > zoomed["data_lo"] or zoomed["hi"] < zoomed["data_hi"], zoomed  # the box cut the data
    assert fitted["lo"] <= fitted["data_lo"] and fitted["hi"] >= fitted["data_hi"], (zoomed, fitted)
    assert span_after_fit == span
