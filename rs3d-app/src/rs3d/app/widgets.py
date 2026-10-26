"""Shared UI pieces: page frame with sidebar (layout A), (?) help icons, status icons."""

from __future__ import annotations

from nicegui import run, ui

from rs3d.app.state import AppState
from rs3d.app.strings import help_text, label
from rs3d.core.discovery import discover
from rs3d.core.models import Device, Level

NAV = (("status", "monitor_heart"), ("live", "show_chart"), ("helicorder", "graphic_eq"), ("frequencies", "query_stats"), ("data", "download"),
       ("guide", "menu_book"), ("settings", "settings"))
LEVEL_ICON = {Level.OK: ("check_circle", "positive"), Level.WARN: ("error", "warning"),
              Level.ERROR: ("cancel", "negative"), Level.SKIPPED: ("remove_circle_outline", "grey-5")}


def help_icon(help_id: str) -> None:
    """(?) icon: hover = short tooltip, click = detail panel."""
    short, detail = help_text(help_id)
    if not short:
        return
    with ui.dialog() as dialog, ui.card().classes("max-w-xl"):
        ui.markdown(detail)
        ui.button(label("action.close"), on_click=dialog.close).props("flat")
    icon = ui.icon("help_outline", size="xs").classes("cursor-pointer text-grey-6")
    icon.on("click", dialog.open)
    icon.tooltip(short)


def level_icon(level: Level) -> None:
    name, color = LEVEL_ICON[level]
    ui.icon(name, color=color, size="sm")


def frame(state: AppState, page: str) -> Device | None:
    """Header + left drawer with devices and pages. Returns the current device (or None)."""
    ui.colors(primary="#0B4F6C", accent="#F15A24")
    with ui.header().classes("items-center py-1 px-3 bg-primary"):
        ui.image("/static/rs3d-icon.svg").classes("w-8 h-8 rounded bg-white p-px")
        ui.label(label("app")).classes("text-lg font-bold")
        ui.label("·").classes("opacity-60")
        ui.label(label(f"nav.{page}"))

    with ui.left_drawer(value=True, bordered=True).props("width=190").classes("p-2 gap-1"):
        ui.label(label("devices")).classes("text-xs uppercase text-grey-7")
        current = state.current()
        for d in state.devices():
            selected = current is not None and d.host == current.host
            ui.button(f"● {d.name}", on_click=lambda d=d: (state.select(d.host), ui.navigate.reload())) \
                .props(f"flat dense no-caps align=left {'color=primary' if selected else 'color=grey-8'}") \
                .classes("w-full")
        ui.button(label("find"), icon="search", on_click=lambda: _find_dialog(state)) \
            .props("flat dense no-caps align=left color=grey-8").classes("w-full")
        ui.separator().classes("my-2")
        for key, icon in NAV:
            ui.button(label(f"nav.{key}"), icon=icon, on_click=lambda key=key: ui.navigate.to(f"/{key}")) \
                .props(f"flat dense no-caps align=left {'color=primary' if key == page else 'color=grey-8'}") \
                .classes("w-full")
    return current


async def _find_dialog(state: AppState) -> None:
    with ui.dialog() as dialog, ui.card().classes("min-w-80"):
        ui.label(label("find")).classes("text-base font-bold")
        box = ui.column()
        with box:
            ui.spinner()
    dialog.open()
    found = await run.io_bound(discover)
    box.clear()
    with box:
        if not found:
            ui.label(label("no_device")).classes("text-grey-7")
        for f in found:
            with ui.row().classes("items-center gap-3"):
                ui.label(f"{f.info.network}.{f.info.station}").classes("font-mono")
                ui.label(f.host).classes("text-grey-7")

                def add(f=f) -> None:
                    state.save_device(Device(name=f.info.station, host=f.host, network=f.info.network,
                                             station=f.info.station, location=f.info.location))
                    dialog.close()
                    ui.navigate.to("/status")

                ui.button(label("action.add"), on_click=add).props("dense")
        ui.button(label("action.close"), on_click=dialog.close).props("flat")
