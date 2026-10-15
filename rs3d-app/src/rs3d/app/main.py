"""Build all pages and start the NiceGUI server."""

from __future__ import annotations

import socket

from nicegui import app, ui

from rs3d.app.pages import data, guide, helicorder, live, settings, status
from rs3d.app.state import AppState
from rs3d.core.paths import AppPaths


def build(state: AppState) -> None:
    for page in (status, live, helicorder, data, guide, settings):
        page.register(state)

    @ui.page("/")
    def index() -> None:
        ui.navigate.to("/status" if state.devices() else "/settings")

    app.on_shutdown(state.stop_all)


def free_port(preferred: int = 8765) -> int:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]


def run(port: int | None = None, show: bool = True, native: bool = False) -> None:
    state = AppState(AppPaths.default())
    build(state)
    ui.run(title="RS3D", host="127.0.0.1", port=port or free_port(), show=show, native=native,
           reload=False, favicon="🌍", show_welcome_message=True)
