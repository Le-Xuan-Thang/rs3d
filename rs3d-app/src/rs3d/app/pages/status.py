"""Status page: one row per check, refreshed every 30 s."""

from __future__ import annotations

import platform
import shlex
import time

from nicegui import run, ui

from rs3d.app.state import AppState
from rs3d.app.strings import label
from rs3d.app.widgets import frame, help_icon, level_icon
from rs3d.core import netcheck
from rs3d.core.clock import log_sync, measure_offset, offset_text, set_from_laptop, sync_now, utc_text
from rs3d.core.shell import ShellError
from rs3d.core.models import Check

_NOT_WIRED = ("lo", "docker", "veth", "virbr", "br-", "tailscale", "wl", "wi-fi", "wlan", "loopback", "utun",
              "awdl", "llw", "bridge", "vmnet", "zt")


def wired_candidates() -> list[str]:
    return [i.name for i in netcheck.interfaces()
            if i.is_up and not i.name.lower().startswith(_NOT_WIRED)]


def log_warning(error: str) -> str:
    """Status-page line when events cannot be saved; '' when all is well."""
    return label("events.log_error").format(error=error) if error else ""


def register(state: AppState) -> None:
    @ui.page("/status")
    def status_page() -> None:
        device = frame(state, "status")
        if device is None:
            ui.label(label("no_device")).classes("text-grey-7")
            return
        with ui.row().classes("items-center gap-3"):
            ui.label(f"{device.name}").classes("text-lg font-bold")
            ui.label(device.host).classes("text-grey-7 font-mono")
            updated = ui.label("").classes("text-xs text-grey-6")
            ui.button(icon="refresh", on_click=lambda: refresh()).props("flat round dense") \
                .tooltip(label("action.refresh"))
        rows = ui.column().classes("gap-0 w-full max-w-2xl")
        with rows:
            ui.spinner()
        dialog_host = ui.element()  # outside `rows`: a page refresh rebuilds `rows` and must not delete an open dialog
        warning = ui.label("").classes("text-sm text-negative")
        stamp = {"t": 0.0}

        def open_dialog(make, *args) -> None:
            dialog_host.clear()
            with dialog_host:
                make(*args)

        def render(checks: list[Check]) -> None:
            rows.clear()
            with rows:
                for c in checks:
                    with ui.row().classes("items-center gap-2 w-full py-1 border-b border-grey-3"):
                        level_icon(c.level)
                        ui.label(label(f"check.{c.id}")).classes("w-36")
                        ui.label(c.value).classes("text-grey-8 font-mono text-sm grow")
                        help_icon(c.help_id or c.id)
                        if c.action == "set_ip":
                            ui.button(label("action.set_ip"), on_click=lambda: open_dialog(set_ip_dialog, refresh)) \
                                .props("dense unelevated")
                        elif c.action == "download":
                            ui.button(label("action.download"), on_click=lambda: ui.navigate.to("/data")) \
                                .props("dense flat")
                        elif c.action == "sync_clock":
                            ui.button(label("action.sync_clock"),
                                      on_click=lambda: open_dialog(sync_clock_dialog, state, device, refresh)) \
                                .props("dense unelevated")

        async def refresh() -> None:
            checks = await run.io_bound(state.checks, device)
            if checks is None:  # client went away
                return
            render(checks)
            stamp["t"] = time.monotonic()

        def tick_label() -> None:
            if stamp["t"]:
                updated.text = f"{int(time.monotonic() - stamp['t'])} s ago"
            warning.text = log_warning(state.events.error)

        ui.timer(0.1, refresh, once=True)
        ui.timer(30, refresh)
        ui.timer(1, tick_label)


def set_ip_dialog(after) -> None:
    system = platform.system()
    names = wired_candidates()
    with ui.dialog() as dialog, ui.card().classes("min-w-96"):
        ui.label(label("setip.title")).classes("text-base font-bold")
        choice = ui.select(names, value=names[0] if names else None, label=label("setip.interface")) \
            .classes("w-full")
        ui.label(label("setip.commands")).classes("text-xs text-grey-7")
        preview = ui.code("", language="bash").classes("w-full")

        async def show() -> None:
            if not choice.value:
                preview.content = ""
                return
            try:
                target = await run.io_bound(netcheck.resolve_target, system, choice.value)
                cmds = netcheck.set_ip_commands(system, choice.value, target)
                preview.content = "\n".join(shlex.join(c) for c in cmds)
            except Exception as exc:
                preview.content = f"# {exc}"

        async def apply() -> None:
            try:
                await run.io_bound(netcheck.set_ip, choice.value, system)
                ui.notify(label("setip.done"), type="positive")
                dialog.close()
                await after()
            except Exception as exc:
                ui.notify(str(exc), type="negative", multi_line=True)

        choice.on_value_change(show)
        with ui.row():
            ui.button(label("action.run"), on_click=apply).props("unelevated")
            ui.button(label("action.cancel"), on_click=dialog.close).props("flat")
    dialog.open()
    ui.timer(0.05, show, once=True)


def sync_clock_dialog(state: AppState, device, after) -> None:
    log_path = state.paths.logs / "clock-sync.log"
    with ui.dialog() as dialog, ui.card().classes("min-w-96 max-w-xl"):
        ui.label(label("clock.title")).classes("text-base font-bold")
        info = ui.label("").classes("font-mono text-sm").style("white-space: pre-line")
        ui.label(label("clock.warning")).classes("text-xs text-grey-7")
        result = ui.label("").classes("text-sm")
        with ui.row():
            sync = ui.button(label("clock.sync_now"), on_click=lambda: act(sync_now)).props("unelevated")
            laptop = ui.button(label("clock.set_laptop"), on_click=lambda: act(set_from_laptop)).props("flat")
            ui.button(label("action.close"), on_click=dialog.close).props("flat")
    laptop.set_visibility(False)  # offered only after Sync now did not work

    def work(action):
        with state.shell(device) as sh:
            return action(sh)

    async def act(action) -> None:
        sync.disable()
        laptop.disable()
        result.text = label("clock.working")
        try:
            res = await run.io_bound(work, action)
        except ShellError as exc:
            result.text = f"{label('clock.failed')} {exc}"
            return
        finally:
            sync.enable()
            laptop.enable()
        log_sync(log_path, res)
        result.text = label("clock.done") if res.ok else f"{label('clock.failed')} {res.message}"
        if not res.ok:
            laptop.set_visibility(True)
        await after()

    async def show() -> None:
        try:
            offset = await run.io_bound(work, measure_offset)
            now = time.time()
            info.text = "\n".join([f"{label('clock.shake_time')}: {utc_text(now + offset)}",
                                  f"{label('clock.laptop_time')}: {utc_text(now)}",
                                  offset_text(offset)])
        except (ShellError, ValueError) as exc:
            info.text = str(exc)

    dialog.open()
    ui.timer(0.05, show, once=True)
