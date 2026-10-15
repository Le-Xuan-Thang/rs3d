"""Detail view for a clicked time: waveform / spectra / spectrogram of about two minutes, with zoom and shift."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from nicegui import run, ui
from obspy import Stream, UTCDateTime

from rs3d.app import timeutil
from rs3d.app.charts import set_stream_data, spectrogram_options, spectrum_options, waveform_options
from rs3d.app.state import AppState
from rs3d.app.strings import label
from rs3d.core.helicorder import load_window, shift_window, zoom_window
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


def inventory_for(state: AppState, net: str, sta: str):
    return cached_inventory(state.paths.response, net, sta) or get_inventory(state.paths.response, net, sta)


def detail_chart_options(mode: str, st: Stream, channel: str, use_utc: bool) -> dict | None:
    """ECharts options for one detail mode, or None when the window has no samples for the channel."""
    traces = st.select(channel=channel)
    if not len(traces) or not sum(tr.stats.npts for tr in traces):
        return None
    if mode == "waveform":
        opt = waveform_options((channel,), use_utc)
        set_stream_data(opt, traces)
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
        self.origin: tuple[UTCDateTime, UTCDateTime] | None = None
        self.window: tuple[UTCDateTime, UTCDateTime] | None = None
        self.mode = "waveform"
        self.stream: Stream | None = None
        with ui.card().classes("w-full") as self.card:
            with ui.row().classes("items-center gap-1"):
                self.title = ui.label("").classes("font-mono text-sm")
                ui.button(icon="fit_screen", on_click=self.fit).props("flat dense round") \
                    .tooltip(label("detail.fit")).mark("detail-fit")
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
                self.extra = ui.row().classes("items-center gap-1")  # the clipboard button goes here
                ui.button(icon="close", on_click=self.close).props("flat dense round").mark("detail-close")
            self.message = ui.label("").classes("text-grey-7")
            self.chart = ui.echart({"series": []}).classes("w-full").style("height: 34vh")
        self.card.set_visibility(False)

    async def open(self, center: UTCDateTime, span: float = 120.0) -> None:
        self.origin = (center - span / 2, center + span / 2)
        self.window = self.origin
        self.card.set_visibility(True)
        await self.reload()

    def close(self) -> None:
        self.card.set_visibility(False)

    async def fit(self) -> None:
        if self.origin:
            self.window = self.origin
            await self.reload()

    async def zoom(self, factor: float) -> None:
        if self.window:
            self.window = zoom_window(*self.window, factor)
            await self.reload()

    async def shift(self, direction: int) -> None:
        if self.window:
            self.window = shift_window(*self.window, direction)
            await self.reload()

    def set_mode(self, _=None) -> None:
        self.mode = self.toggle.value
        self.draw()

    async def reload(self) -> None:
        if self.window is None:
            return
        ctx, (a, b) = self.get_ctx(), self.window

        def work() -> Stream:
            inv = inventory_for(self.state, ctx.net, ctx.sta) if ctx.units == "m/s" else None
            return load_window(self.state.store, ctx.net, ctx.sta, ctx.loc, ctx.channel, a, b,
                               ctx.units, ctx.band, inv)

        try:
            self.stream = await run.io_bound(work)
        except Exception as exc:
            ui.notify(str(exc), type="negative", multi_line=True)
            return
        self.draw()

    def draw(self) -> None:
        if self.window is None or self.stream is None:
            return
        ctx = self.get_ctx()
        a, b = self.window
        self.title.text = (f"{ctx.net}.{ctx.sta}.{ctx.loc}.{ctx.channel}  "
                           f"{timeutil.to_text(a, not ctx.use_utc)} → {timeutil.to_text(b, not ctx.use_utc)}")
        options = detail_chart_options(self.mode, self.stream, ctx.channel, ctx.use_utc)
        if options is None:
            self.message.text = label("detail.no_window_data")
            self.chart.set_visibility(False)
            return
        self.message.text = ""
        self.chart.set_visibility(True)
        self.chart.options.clear()
        self.chart.options.update(options)
        self.chart.update()
