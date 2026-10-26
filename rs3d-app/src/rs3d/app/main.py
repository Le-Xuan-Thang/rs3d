"""Build all pages and start the NiceGUI server."""

from __future__ import annotations

import socket
from pathlib import Path

from nicegui import app, ui

from rs3d.app.pages import data, guide, helicorder, live, settings, status
from rs3d.app.state import AppState
from rs3d.core.paths import AppPaths


STATIC = Path(__file__).parent / "static"


def build(state: AppState) -> None:
    app.add_static_files("/static", STATIC)
    for page in (status, live, helicorder, data, guide, settings):
        page.register(state)

    @ui.page("/")
    def index() -> None:
        ui.navigate.to("/status" if state.devices() else "/settings")

    app.on_startup(state.start_current)  # detection runs without the Live page open
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
    state = AppState(AppPaths.default(), preload=True)
    build(state)
    ui.run(title="RS3D", host="127.0.0.1", port=port or free_port(), show=show, native=native,
           reload=False, favicon=STATIC / "rs3d-icon.png", show_welcome_message=not native,
           **({"window_size": (1400, 900)} if native else {}))
