"""Live page: three channels in real time."""

from __future__ import annotations

import time
from datetime import date, datetime, timezone
from urllib.parse import urlencode

from nicegui import ui

from rs3d.app.charts import (helicorder_height_px, helicorder_options, set_event_areas, set_helicorder_events,
                             set_live_data, waveform_options)
from rs3d.app.pages.helicorder import SCALES
from rs3d.app.state import CHANNELS, AppState
from rs3d.app.strings import label
from rs3d.app.widgets import frame, help_icon
from rs3d.core.events import Event
from rs3d.core.helicorder import scale_for
from rs3d.core.models import Device

WINDOWS = {30: "30 s", 60: "60 s", 300: "5 min", 600: "10 min"}  # the ring buffer keeps 10 min
LIVE_FILTER = (1.0, 10.0)
HELI_REFRESH = 5.0  # seconds between redraws of the 48-row chart


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


def clock(t: float, local: bool) -> str:
    return datetime.fromtimestamp(t, None if local else timezone.utc).strftime("%H:%M:%S")


def banner_state(open_event: tuple[float, float] | None, last: Event | None, local: bool) -> tuple[str, str]:
    """('active' | 'ended' | '', text) for the event banner."""
    if open_event is not None:
        start, ratio = open_event
        return "active", label("events.active").format(start=clock(start, local), ratio=f"{ratio:.1f}")
    if last is not None:
        return "ended", label("events.ended").format(duration=round(last.end - last.start),
                                                    ratio=f"{last.peak_ratio:.1f}",
                                                    amplitude=round(last.peak_amplitude))
    return "", ""


def event_row_text(e: Event, local: bool) -> str:
    return f"{clock(e.start, local)}   {round(e.end - e.start)} s   ratio {e.peak_ratio:.1f}   {e.source}"


def live_spans(recent, open_event: tuple[float, float] | None,
               window: tuple[float, float]) -> list[tuple[float, float]]:
    """Event spans to shade in the visible window; an event in progress runs up to the window's end."""
    spans = [(e.start, e.end) for e in recent if e.end >= window[0] and e.start <= window[1]]
    if open_event is not None:
        spans.append((open_event[0], window[1]))
    return spans


def heli_spans(events, channel: str, open_event: tuple[float, float] | None, detect_channel: str,
               until: float) -> list[tuple[float, float]]:
    """Event spans to shade on the live helicorder; an event in progress runs up to `until` (the newest data)."""
    spans = [(e.start, e.end) for e in events if e.channel == channel]
    if open_event is not None and channel == detect_channel:
        spans.append((open_event[0], max(until, open_event[0])))
    return spans


def heli_options(rows, factor: float, spans: list[tuple[float, float]]) -> dict:
    options = helicorder_options(rows, scale_for(rows, factor))
    set_helicorder_events(options, rows, spans)
    return options


def helicorder_link(device: Device, channel: str, day: date) -> str:
    """The same day on the Helicorder page (it reads the files in the local store)."""
    return "/helicorder?" + urlencode({"station": f"{device.network}.{device.station}.{device.location}",
                                       "channel": channel, "day": day.isoformat()})


def register(state: AppState) -> None:
    @ui.page("/live")
    def live_page() -> None:
        device = frame(state, "live")
        if device is None:
            ui.label(label("no_device")).classes("text-grey-7")
            return
        stream = state.live(device)
        view = {"paused": False, "heli_at": 0.0}
        days = state.day_trace(device)

        with ui.row().classes("items-center gap-1"):
            mode = ui.toggle({"wave": label("live.mode_wave"), "heli": label("live.mode_heli")}, value=state.live_view["mode"]) \
                .props("dense no-caps")
            help_icon("live_heli")
            status = ui.label("").classes("text-sm text-grey-7 ml-4")

        heli_controls = ui.row().classes("items-center gap-4")
        with heli_controls:
            heli_channel = ui.select(list(CHANNELS), value=state.live_view["channel"]).props("dense").classes("w-24")
            heli_scale = ui.select(SCALES, value=state.live_view["scale"], label=label("heli.scale")).props("dense").classes("w-24")
            ui.button(label("live.open_heli"), icon="open_in_new",
                      on_click=lambda: ui.navigate.to(helicorder_link(device, heli_channel.value, days.day))) \
                .props("flat dense no-caps")
        heli_empty = ui.label(label("live.heli_empty")).classes("text-sm text-grey-7")
        heli_controls.set_visibility(False)
        heli_empty.set_visibility(False)

        wave_controls = ui.row().classes("items-center gap-4")
        with wave_controls:
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

        banner = ui.row().classes("w-full items-center gap-2 px-3 py-1 text-white")
        with banner:
            banner_text = ui.label("").classes("font-bold grow")
            ui.button(label("events.dismiss"), on_click=lambda: setattr(state, "event_last", None)) \
                .props("flat dense no-caps color=white")
        banner.set_visibility(False)

        chart = ui.echart(waveform_options(CHANNELS, use_utc=not state.use_local_time)) \
            .classes("w-full").style("height: 72vh")
        heli_chart = ui.echart({"series": []}).classes("w-full").style(f"height: {helicorder_height_px(48)}px")
        heli_chart.set_visibility(False)
        ui.label(label("events.latest")).classes("font-bold mt-2")
        event_list = ui.column().classes("gap-0 font-mono text-sm")
        listed = {"key": None}

        def toggle_pause() -> None:
            view["paused"] = not view["paused"]
            pause.text = label("action.resume") if view["paused"] else label("action.pause")
            pause.props(f"icon={'play_arrow' if view['paused'] else 'pause'}")

        pause.on_click(toggle_pause)

        def set_mode(_=None) -> None:
            heli = mode.value == "heli"
            wave_controls.set_visibility(not heli)
            chart.set_visibility(not heli)
            heli_controls.set_visibility(heli)
            heli_chart.set_visibility(heli)
            heli_empty.set_visibility(heli and not days.has_data(heli_channel.value))
            state.live_view["mode"] = mode.value
            view["heli_at"] = 0.0  # draw at once

        def set_heli_channel(_=None) -> None:
            state.live_view["channel"] = heli_channel.value
            view["heli_at"] = 0.0

        def set_heli_scale(_=None) -> None:
            state.live_view["scale"] = heli_scale.value
            view["heli_at"] = 0.0

        mode.on_value_change(set_mode)
        heli_channel.on_value_change(set_heli_channel)
        heli_scale.on_value_change(set_heli_scale)
        set_mode()  # a remembered helicorder mode shows its controls and draws at once

        def draw_helicorder(recent_open) -> None:
            if time.monotonic() - view["heli_at"] < HELI_REFRESH:
                return
            view["heli_at"] = time.monotonic()
            channel = heli_channel.value
            rows = days.rows(channel)
            heli_empty.set_visibility(not days.has_data(channel))
            until = stream.buffer.latest() or days.start
            events = state.events.events_between(days.start, days.start + 86400)
            spans = heli_spans(events, channel, recent_open, state.event_settings.channel, until)
            heli_chart.options.clear()
            heli_chart.options.update(heli_options(rows, float(heli_scale.value), spans))
            heli_chart.update()

        def tick() -> None:
            status.text = status_text(stream.state, stream.is_stale(), stream.error)
            kind, text = banner_state(state.event_open, state.event_last, state.use_local_time)
            banner.set_visibility(bool(kind))
            banner_text.text = text
            banner.style(f"background: {'#c62828' if kind == 'active' else '#ef6c00'}")
            recent = list(state.recent_events)
            key = (len(recent), recent[-1].start if recent else None, state.use_local_time)
            if key != listed["key"]:
                listed["key"] = key
                event_list.clear()
                with event_list:
                    if not recent:
                        ui.label(label("events.none")).classes("text-grey-6")
                    for e in reversed(recent[-8:]):
                        ui.label(event_row_text(e, state.use_local_time))
            if mode.value == "heli":
                draw_helicorder(state.event_open)
                return
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
            set_event_areas(chart.options, live_spans(recent, state.event_open, (end - seconds, end)))
            chart.update()

        def save_segment() -> None:
            end = stream.buffer.latest()
            if end is None:
                return
            ui.navigate.to(f"/data?start={int(end - window.value)}&end={int(end) + 1}")

        ui.timer(0.25, tick)
