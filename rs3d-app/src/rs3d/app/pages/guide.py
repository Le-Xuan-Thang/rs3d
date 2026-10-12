"""Guide page: the bundled Markdown manual."""

from __future__ import annotations

from nicegui import ui

from rs3d.app.state import AppState
from rs3d.app.strings import guide_markdown
from rs3d.app.widgets import frame


def register(state: AppState) -> None:
    @ui.page("/guide")
    def guide_page() -> None:
        frame(state, "guide")
        ui.markdown(guide_markdown()).classes("max-w-3xl")
