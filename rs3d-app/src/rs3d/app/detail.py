"""Detail view for a clicked time: waveform / spectra / spectrogram of about two minutes, with zoom and shift."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from nicegui import run, ui
from obspy import Stream, UTCDateTime

from rs3d.app import timeutil
from rs3d.app.charts import set_stream_data, spectrogram_options, spectrum_options, waveform_options
from rs3d.app.latest import LatestOnly
from rs3d.app.state import AppState
from rs3d.app.strings import label
from rs3d.core.export import clipboard_title, write_clipboard_png
from rs3d.core.helicorder import box_window, load_window, shift_window, zoom_window
from rs3d.core.response import cached_inventory, get_inventory
from rs3d.core.spectro import amplitude_spectrum, spectrogram, window_for

MODES = ("waveform", "spectra", "spectrogram")


@dataclass(frozen=True)
class DetailContext:
    net: str
    sta: str
    loc: str
    channel: str
    units: str
    band: tuple[float, float] | None
    use_utc: bool


@dataclass(frozen=True)
class Loaded:
    """What is on screen: the data, and the context and window it was loaded with."""

    ctx: DetailContext
    window: tuple[UTCDateTime, UTCDateTime]
    stream: Stream


def detail_title(ctx: DetailContext, window: tuple[UTCDateTime, UTCDateTime]) -> str:
    a, b = window
    text = (f"{ctx.net}.{ctx.sta}.{ctx.loc}.{ctx.channel}  "
            f"{timeutil.to_text(a, not ctx.use_utc)} → {timeutil.to_text(b, not ctx.use_utc)}  {ctx.units}")
    if ctx.band is not None:
        text += f"  band-pass {ctx.band[0]:g}–{ctx.band[1]:g} Hz"
    return text


def box_from_event(args: dict) -> tuple[float, float, float, float] | None:
    """(x0_ms, x1_ms, y0, y1) from an ECharts brushEnd event, or None when no rectangle was drawn."""
    areas = (args or {}).get("areas") or []
    if not areas:
        return None
    (x0, x1), (y0, y1) = areas[0]["coordRange"]
    return float(x0), float(x1), float(y0), float(y1)


def inventory_for(state: AppState, net: str, sta: str):
    return cached_inventory(state.paths.response, net, sta) or get_inventory(state.paths.response, net, sta)


BRUSH = {"xAxisIndex": 0, "yAxisIndex": 0, "brushType": "rect", "brushMode": "single", "transformable": False,
         "toolbox": [],  # no built-in brush buttons: the Box zoom button switches the drag on
         "brushStyle": {"borderWidth": 1, "color": "rgba(47,111,222,0.2)", "borderColor": "#2f6fde"}}


def detail_chart_options(mode: str, st: Stream, channel: str, use_utc: bool,
                         y_range: tuple[float, float] | None = None) -> dict | None:
    """ECharts options for one detail mode, or None when the window has no samples for the channel.

    The waveform gets a rectangle brush (for box zoom) and, when `y_range` is given, a fixed amplitude range.
    """
    traces = st.select(channel=channel)
    if not len(traces) or not sum(tr.stats.npts for tr in traces):
        return None
    if mode == "waveform":
        opt = waveform_options((channel,), use_utc)
        set_stream_data(opt, traces)
        opt["brush"] = dict(BRUSH)
        opt["toolbox"] = {"show": False}  # without this the brush adds its own buttons on the first draw
        # always set min/max: the chart merges options, so leaving them out would keep an old box-zoom range
        opt["yAxis"][0]["min"], opt["yAxis"][0]["max"] = y_range if y_range is not None else (None, None)
        return opt
    merged = traces.copy().merge(method=0)[0]
    if mode == "spectra":
        return spectrum_options(*amplitude_spectrum(merged))
    if mode == "spectrogram":
        return spectrogram_options(*spectrogram(merged, window_for(merged.stats.endtime - merged.stats.starttime)),
                                   use_utc=use_utc)
    raise ValueError(f"unknown mode {mode!r}")


class DetailPanel:
    """Hidden until `open()`. Loads its own data from the local archive."""

    def __init__(self, state: AppState, get_ctx: Callable[[], DetailContext]) -> None:
        self.state, self.get_ctx = state, get_ctx
        self.window: tuple[UTCDateTime, UTCDateTime] | None = None
        self.mode = "waveform"
        self.y_range: tuple[float, float] | None = None  # amplitude zoom set by box zoom
        self.box_on = False
        self.loaded: Loaded | None = None
        self._drawn_mode = "waveform"
        self._latest = LatestOnly()
        with ui.card().classes("w-full") as self.card:
            with ui.row().classes("items-center gap-1"):
                self.title = ui.label("").classes("font-mono text-sm")
                ui.button(icon="fit_screen", on_click=self.fit).props("flat dense round data-testid=fit") \
                    .tooltip(label("detail.fit")).mark("detail-fit")
                self.box_button = ui.button(icon="crop_free", on_click=self.toggle_box).props(
                    "flat dense round data-testid=box-zoom").tooltip(label("detail.box_zoom"))
                ui.button(icon="remove", on_click=lambda: self.zoom(2.0)).props("flat dense round") \
                    .tooltip(label("detail.zoom_out")).mark("detail-zoom-out")
                ui.button(icon="add", on_click=lambda: self.zoom(0.5)).props("flat dense round") \
                    .tooltip(label("detail.zoom_in")).mark("detail-zoom-in")
                ui.button(icon="chevron_left", on_click=lambda: self.shift(-1)).props("flat dense round") \
                    .tooltip(label("detail.earlier")).mark("detail-earlier")
                ui.button(icon="chevron_right", on_click=lambda: self.shift(1)).props("flat dense round") \
                    .tooltip(label("detail.later")).mark("detail-later")
                self.toggle = ui.toggle({m: label(f"detail.{m}") for m in MODES}, value="waveform",
                                        on_change=self.set_mode).props("dense no-caps")
                ui.button(icon="content_paste", on_click=self.open_clipboard).props(
                    "flat dense round data-testid=clipboard").tooltip(label("clipboard.title"))
                ui.button(icon="close", on_click=self.close).props("flat dense round").mark("detail-close")
            self.message = ui.label("").classes("text-grey-7")
            self.chart = ui.echart({"series": []}).classes("w-full").style("height: 34vh")
            self.chart.on("chart:brushEnd", self.on_brush)
        self.card.set_visibility(False)

    async def go(self, window: tuple[UTCDateTime, UTCDateTime], y_range: tuple[float, float] | None = None) -> bool:
        """Show `window` with the given amplitude zoom; both are only kept when the load succeeds."""
        previous, self.y_range = self.y_range, y_range
        ok = await self.load(window)
        if not ok:
            self.y_range = previous
        return ok

    async def open(self, center: UTCDateTime, span: float = 120.0) -> None:
        if await self.go((center - span / 2, center + span / 2)):
            self.card.set_visibility(True)

    def close(self) -> None:
        self.card.set_visibility(False)

    async def fit(self) -> None:
        """Rescale the amplitude to the data in view; the time window (and its width) stays as it is."""
        if self.window:
            await self.go(self.window)

    async def zoom(self, factor: float) -> None:
        if self.window:
            await self.go(zoom_window(*self.window, factor))

    async def shift(self, direction: int) -> None:
        if self.window:
            await self.go(shift_window(*self.window, direction))

    async def apply_box(self, x0_ms: float, x1_ms: float, y0: float, y1: float) -> None:
        """Zoom into a dragged rectangle: its time edges become the window, its amplitude edges the y range."""
        if self.window:
            low, high = (float(f"{v:.4g}") for v in (min(y0, y1), max(y0, y1)))  # readable axis labels
            await self.go(box_window(self.window, x0_ms, x1_ms), (low, high))

    async def reload(self) -> None:
        """Load the current window again, with the page's current units and band-pass."""
        if self.window:
            await self.load(self.window)

    async def reload_if_open(self) -> None:
        if self.card.visible:
            await self.reload()

    def toggle_box(self) -> None:
        self.box_on = not self.box_on
        self.box_button.props(f"color={'primary' if self.box_on else 'grey-8'}")
        self.apply_cursor()

    def apply_cursor(self) -> None:
        """Switch the chart's drag cursor between box select and normal."""
        on = self.box_on and self.mode == "waveform"
        self.chart.run_chart_method("dispatchAction", {
            "type": "takeGlobalCursor", "key": "brush",
            "brushOption": {"brushType": "rect", "brushMode": "single"} if on else False})

    async def on_brush(self, e) -> None:
        box = box_from_event(e.args)
        self.chart.run_chart_method("dispatchAction", {"type": "brush", "areas": []})  # clear the drawn rectangle
        if box is not None:
            await self.apply_box(*box)

    def set_mode(self, _=None) -> None:
        self.mode = self.toggle.value
        self.draw()
        self.apply_cursor()

    async def load(self, window: tuple[UTCDateTime, UTCDateTime]) -> bool:
        """Load `window`; the panel only changes (window, data, chart) when this load succeeds and is the newest."""
        token = self._latest.next()
        ctx, (a, b) = self.get_ctx(), window

        def work() -> Stream:
            inv = inventory_for(self.state, ctx.net, ctx.sta) if ctx.units == "m/s" else None
            return load_window(self.state.store, ctx.net, ctx.sta, ctx.loc, ctx.channel, a, b,
                               ctx.units, ctx.band, inv)

        try:
            st = await run.io_bound(work)
        except Exception as exc:
            if self._latest.is_current(token):
                ui.notify(str(exc), type="negative", multi_line=True)
            return False
        if not self._latest.is_current(token):
            return False
        self.window = window
        self.loaded = Loaded(ctx, window, st)
        self.draw()
        return True

    async def save_clipboard(self) -> Path | None:
        """Render the clipboard PNG for what is on screen and offer it for download; None if it cannot be made."""
        if self.loaded is None:
            return None
        ctx, (a, b), st = self.loaded.ctx, self.loaded.window, self.loaded.stream.select(channel=self.loaded.ctx.channel)
        title = clipboard_title(ctx.net, ctx.sta, ctx.loc, ctx.channel, a, b, ctx.units, ctx.band)
        out = Path(tempfile.mkdtemp()) / f"{ctx.net}.{ctx.sta}.{ctx.channel}_{a.strftime('%Y%m%dT%H%M%S')}.png"
        try:
            await run.io_bound(write_clipboard_png, st, out, title, ctx.units)
        except Exception as exc:
            ui.notify(str(exc), type="negative", multi_line=True)
            return None
        ui.download.file(out, out.name)
        return out

    def open_clipboard(self) -> None:
        """Dialog with waveform, spectrogram and spectrum of what is on screen; the camera saves a PNG."""
        if self.loaded is None:
            return
        ctx, st = self.loaded.ctx, self.loaded.stream.select(channel=self.loaded.ctx.channel)
        with ui.dialog() as dialog, ui.card().classes("w-full max-w-6xl"):
            with ui.row().classes("items-center w-full"):
                ui.label(label("clipboard.title")).classes("text-lg font-bold")
                ui.space()
                ui.button(icon="photo_camera", on_click=self.save_clipboard).props("flat round data-testid=camera") \
                    .tooltip(label("clipboard.camera"))
                ui.button(icon="close", on_click=dialog.close).props("flat round")
            for mode, height in (("waveform", "22vh"), ("spectrogram", "26vh"), ("spectra", "26vh")):
                options = detail_chart_options(mode, st, ctx.channel, ctx.use_utc)
                if options is None:
                    ui.label(label("detail.no_window_data")).classes("text-grey-7")
                    break
                ui.echart(options).classes("w-full").style(f"height: {height}")
        dialog.open()

    def draw(self) -> None:
        if self.loaded is None:
            return
        ctx, window, st = self.loaded.ctx, self.loaded.window, self.loaded.stream
        self.title.text = detail_title(ctx, window)
        options = detail_chart_options(self.mode, st, ctx.channel, ctx.use_utc, self.y_range)
        if options is None:
            self.message.text = label("detail.no_window_data")
            self.chart.set_visibility(False)
            return
        self.message.text = ""
        self.chart.set_visibility(True)
        self.chart.options.clear()
        self.chart.options.update(options)
        if self._drawn_mode != self.mode:
            # The chart merges option updates when the series count is unchanged, so components of the previous
            # mode (for example the spectrogram's colour scale) would stay on screen: replace everything at once.
            self.chart.run_chart_method("setOption", options, True)
            self._drawn_mode = self.mode
        else:
            self.chart.update()
        if self.box_on:
            self.apply_cursor()  # a redraw resets the cursor
