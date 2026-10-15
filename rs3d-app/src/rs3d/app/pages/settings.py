"""Settings page: per-device connection settings and app-wide options."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from nicegui import run, ui

from rs3d.app.state import CHANNELS, AppState
from rs3d.app.strings import label
from rs3d.app.widgets import frame, help_icon
from rs3d.core.events import EventSettings, validate_settings
from rs3d.core.models import Device
from rs3d.core.shell import ShellError

EVENT_NUMBERS = ("sta", "lta", "on", "reset", "highpass", "lowpass")
EVENT_HELP = {"sta": "events.sta", "lta": "events.lta", "on": "events.on", "reset": "events.reset",
              "highpass": "events.band", "lowpass": "events.band"}


def event_settings_from_form(base: EventSettings, enabled: bool, channel: str,
                             numbers: dict) -> tuple[EventSettings | None, str]:
    """(settings, '') for a usable form, else (None, why not). `numbers` maps field name to value or None."""
    if any(numbers.get(k) is None for k in EVENT_NUMBERS):
        return None, label("events.error_empty")
    new = replace(base, enabled=bool(enabled), channel=channel, **{k: float(numbers[k]) for k in EVENT_NUMBERS})
    error = validate_settings(new)
    return (None, error) if error else (new, "")


def channel_note(enabled: bool, channel: str, seen: set[str]) -> str:
    """Warning for the Events card when data arrives but not from the chosen channel; '' otherwise."""
    if not enabled or not seen or channel in seen:
        return ""
    return label("events.missing_channel").format(channel=channel)


def register(state: AppState) -> None:
    @ui.page("/settings")
    def settings_page() -> None:
        current = frame(state, "settings")
        ui.label(label("settings.device")).classes("text-base font-bold")
        with ui.card().classes("w-full max-w-xl"):
            name = ui.input(label("settings.name"), value=current.name if current else "").classes("w-full")
            host = ui.input(label("settings.host"), value=current.host if current else "").classes("w-full")
            port = ui.number(label("settings.port"), value=current.seedlink_port if current else 18000,
                             format="%d").classes("w-full")
            user = ui.input(label("settings.user"), value=current.ssh_user if current else "myshake") \
                .classes("w-full")
            password = ui.input(label("settings.password"), password=True, password_toggle_button=True) \
                .classes("w-full")
            key = ui.input(label("settings.key"),
                           value=str(current.key_path) if current and current.key_path else "").classes("w-full")

            def build() -> Device:
                base = current or Device(name="", host="")
                return Device(name=name.value.strip() or host.value.strip(), host=host.value.strip(),
                              seedlink_port=int(port.value or 18000), ssh_user=user.value.strip() or "myshake",
                              key_path=Path(key.value.strip()) if key.value.strip() else None,
                              network=base.network, station=base.station or name.value.strip(),
                              location=base.location)

            async def test() -> None:
                device = build()
                if password.value:
                    state.passwords.set(device.host, password.value)
                try:
                    await run.io_bound(state.test_connection, device)
                    ui.notify(label("settings.ok"), type="positive")
                except ShellError as exc:
                    ui.notify(str(exc), type="negative")

            def save() -> None:
                if not host.value.strip():
                    return
                state.save_device(build(), password.value or None)
                ui.notify(label("settings.saved"), type="positive")
                ui.navigate.reload()

            def remove() -> None:
                if current:
                    state.remove_device(current.host)
                    ui.navigate.reload()

            with ui.row():
                ui.button(label("action.save"), on_click=save).props("unelevated")
                ui.button(label("action.test"), on_click=test).props("flat")
                if current:
                    ui.button(label("action.remove"), on_click=remove).props("flat color=negative")
                ui.button(label("settings.new"), on_click=lambda: (setattr(state, "current_host", None),
                                                                   ui.navigate.reload())).props("flat")

        ui.label(label("settings.app")).classes("text-base font-bold mt-4")
        with ui.card().classes("w-full max-w-xl"):
            with ui.row().classes("items-center gap-2"):
                ui.label(label("settings.timezone"))
                ui.toggle({False: label("data.utc"), True: label("data.local")}, value=state.use_local_time,
                          on_change=lambda e: state.set_use_local_time(e.value)).props("dense no-caps")
                help_icon("timezone")
            with ui.row().classes("items-center gap-2"):
                ui.label(label("settings.data_dir"))
                ui.label(str(state.paths.root)).classes("font-mono text-sm text-grey-8")

        ui.label(label("settings.events")).classes("text-base font-bold mt-4")
        with ui.card().classes("w-full max-w-xl"):
            ev = state.event_settings
            with ui.row().classes("items-center gap-2"):
                enabled = ui.switch(label("events.enabled"), value=ev.enabled)
                help_icon("events")
            channel = ui.select(list(CHANNELS), value=ev.channel, label=label("events.channel")) \
                .props("dense").classes("w-28")
            fields = {}
            for key in EVENT_NUMBERS:
                with ui.row().classes("items-center gap-2"):
                    fields[key] = ui.number(label(f"events.{key}"), value=getattr(ev, key), format="%.2f") \
                        .props("dense").classes("w-36")
                    help_icon(EVENT_HELP[key])
            note = ui.label("").classes("text-sm text-negative")

            def show_note() -> None:
                note.text = channel_note(state.event_settings.enabled, state.event_settings.channel,
                                         state.live_channels(current)) if current else ""

            def fill(s: EventSettings) -> None:
                enabled.value, channel.value = s.enabled, s.channel
                for k in EVENT_NUMBERS:
                    fields[k].value = getattr(s, k)

            def apply() -> None:
                new, error = event_settings_from_form(state.event_settings, enabled.value, channel.value,
                                                      {k: f.value for k, f in fields.items()})
                error = error or state.set_event_settings(new)
                if error:
                    ui.notify(error, type="negative")
                    return
                ui.notify(label("events.applied"), type="positive")
                show_note()

            def defaults() -> None:
                state.reset_event_settings()
                fill(state.event_settings)
                ui.notify(label("events.applied"), type="positive")
                show_note()

            with ui.row():
                ui.button(label("events.apply"), on_click=apply).props("unelevated dense")
                ui.button(label("events.defaults"), on_click=defaults).props("flat dense no-caps")
            ui.label(label("events.soon")).classes("text-sm text-grey-6")
            show_note()
            ui.timer(5, show_note)
