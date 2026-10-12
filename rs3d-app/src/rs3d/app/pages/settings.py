"""Settings page: per-device connection settings and app-wide options."""

from __future__ import annotations

from pathlib import Path

from nicegui import run, ui

from rs3d.app.state import AppState
from rs3d.app.strings import label
from rs3d.app.widgets import frame, help_icon
from rs3d.core.models import Device
from rs3d.core.shell import ShellError


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
