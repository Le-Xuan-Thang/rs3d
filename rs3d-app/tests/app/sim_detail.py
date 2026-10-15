"""NiceGUI app for DetailPanel tests: one page that builds a panel, and a handle to it in REG."""

import os
from pathlib import Path

from nicegui import context, ui

from rs3d.app.detail import DetailContext, DetailPanel
from rs3d.app.state import AppState
from rs3d.core.devices import Passwords
from rs3d.core.paths import AppPaths
from tests.app.registry import REG, NoKeyring

state = AppState(AppPaths(Path(os.environ["RS3D_DATA_DIR"])), passwords=Passwords(NoKeyring()))
REG["ctx"] = {"ctx": DetailContext("AM", "R77A7", "00", "EHZ", "counts", None, True)}


@ui.page("/t")
def page() -> None:
    REG["panel"] = DetailPanel(state, lambda: REG["ctx"]["ctx"])
    REG["client"] = context.client


ui.run(reload=False)
