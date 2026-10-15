"""Live page: three channels in real time."""

from __future__ import annotations

from nicegui import ui

from rs3d.app.charts import set_live_data, waveform_options
from rs3d.app.state import CHANNELS, AppState
from rs3d.app.strings import label
from rs3d.app.widgets import frame, help_icon

WINDOWS = {30: "30 s", 60: "60 s", 300: "5 min", 600: "10 min"}  # the ring buffer keeps 10 min
LIVE_FILTER = (1.0, 10.0)


def status_text(state_key: str, stale: bool, error: str) -> str:
    """Connection line: while reconnecting, also say why (e.g. connection refused)."""
    if state_key == "live" and stale:
        state_key = "waiting"
    text = label(f"live.{state_key}")
    return f"{text} ({error})" if state_key == "reconnecting" and error else text


def band_for(enabled: bool, fmin: float | None, fmax: float | None) -> tuple[float, float] | None:
    """The band-pass to apply, or None when it is off or the two numbers are not a valid band."""
    if not enabled or not fmin or not fmax or fmin <= 0 or fmax <= fmin:
        return None
    return float(fmin), float(fmax)


def register(state: AppState) -> None:
    @ui.page("/live")
    def live_page() -> None:
        device = frame(state, "live")
        if device is None:
            ui.label(label("no_device")).classes("text-grey-7")
            return
        stream = state.live(device)
        view = {"paused": False}

        with ui.row().classes("items-center gap-4"):
            window = ui.toggle(WINDOWS, value=60).props("dense no-caps")
            with ui.row().classes("items-center gap-1"):
                flt = ui.switch(label("live.filter"), value=True)
                help_icon("live_filter")
            fmin = ui.number(value=LIVE_FILTER[0], min=0.01, step=0.5, format="%.2f").props("dense").classes("w-20")
            fmax = ui.number(value=LIVE_FILTER[1], min=0.02, step=0.5, format="%.2f").props("dense").classes("w-20")
            ui.label("Hz")
            pause = ui.button(label("action.pause"), icon="pause").props("flat dense no-caps")
            ui.button(label("action.save_segment"), icon="content_cut", on_click=lambda: save_segment()) \
                .props("flat dense no-caps")
            status = ui.label("").classes("text-sm text-grey-7")

        chart = ui.echart(waveform_options(CHANNELS, use_utc=not state.use_local_time)) \
            .classes("w-full").style("height: 72vh")

        def toggle_pause() -> None:
            view["paused"] = not view["paused"]
            pause.text = label("action.resume") if view["paused"] else label("action.pause")
            pause.props(f"icon={'play_arrow' if view['paused'] else 'pause'}")

        pause.on_click(toggle_pause)

        def tick() -> None:
            status.text = status_text(stream.state, stream.is_stale(), stream.error)
            if view["paused"]:
                return
            end = stream.buffer.latest()
            if end is None:
                return
            seconds = window.value
            bandpass = band_for(flt.value, fmin.value, fmax.value)
            snaps = {ch: stream.buffer.snapshot(ch, seconds, end, max_points=1500, bandpass=bandpass)
                     for ch in CHANNELS}
            set_live_data(chart.options, snaps, (end - seconds, end))
            chart.update()

        def save_segment() -> None:
            end = stream.buffer.latest()
            if end is None:
                return
            ui.navigate.to(f"/data?start={int(end - window.value)}&end={int(end) + 1}")

        ui.timer(0.25, tick)
