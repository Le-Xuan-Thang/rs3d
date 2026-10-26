"""Frequencies page: pick a time range, find the frequencies the structure vibrates at."""

from __future__ import annotations

import tempfile
from pathlib import Path
from urllib.parse import urlencode

from nicegui import run, ui
from obspy import UTCDateTime

from rs3d.app import timeutil
from rs3d.app.charts import frequency_options
from rs3d.app.detail import inventory_for
from rs3d.app.pages.data import default_range, station_choices
from rs3d.app.state import AppState
from rs3d.app.strings import label
from rs3d.app.widgets import frame, help_icon
from rs3d.core.frequencies import STABLE, Analysis, analyse, stable_lines
from rs3d.core.frequencies_export import write_figure, write_peaks_csv, write_spectra_csv
from rs3d.core.models import Selection
from rs3d.core.response import cached_inventory

PRESETS = ("last_hour", "today", "yesterday", "last_7_days")
MAX_DAYS = 14  # one analysis loads one day at a time, but keep the wait reasonable


def summary_text(a: Analysis) -> str:
    """One plain sentence: the stable frequencies, or why there are none."""
    if not a.channels:
        return label("freq.no_data")
    lines = stable_lines(a)
    if not lines:
        return label("freq.no_stable")
    parts = [f"{f:.2f} Hz ({', '.join(c[-1] for c in chans)})" for f, chans, _ in lines[:6]]
    return label("freq.found").format(freqs="; ".join(parts), pct=round(100 * STABLE))


def peak_rows(a: Analysis) -> list[dict]:
    rows = []
    for ch, r in a.channels.items():
        for p in r.peaks:
            rows.append({"channel": ch, "freq": f"{p.freq:.2f}", "contrast": f"{p.contrast_db:.1f}",
                         "occurrence": f"{100 * p.occurrence:.0f}", "spread": f"{p.p10:.2f}–{p.p90:.2f}",
                         "stable": "●" if p.occurrence >= STABLE else ""})
    return rows


def register(state: AppState) -> None:
    @ui.page("/frequencies")
    def frequencies_page(station: str | None = None, start: str | None = None, end: str | None = None) -> None:
        device = frame(state, "frequencies")
        choices = station_choices(state, device)
        if not choices:
            ui.label(label("data.empty")).classes("text-grey-7")
            return
        remembered = state.data_prefs["station"]
        key = station if station in choices else (remembered if remembered in choices else choices[0])
        net, sta, loc = key.split(".")
        channels = tuple(state.store.channels(net, sta, loc))
        if not channels:
            ui.label(label("data.nothing")).classes("text-grey-7")
            return
        if start and end:
            sel = [UTCDateTime(float(start)), UTCDateTime(float(end))]
        else:
            sel = list(default_range(state, net, sta, loc, channels[0]))
            sel[0] = max(sel[0], sel[1] - 86400)  # the newest day of data
        has_response = cached_inventory(state.paths.response, net, sta) is not None
        result: dict = {"analysis": None}

        with ui.row().classes("items-center gap-2"):
            picker = ui.select(choices, value=key, label=label("data.station")).props("dense").classes("w-56")
            picker.on_value_change(lambda e: ui.navigate.to("/frequencies?" + urlencode({"station": e.value})))
            help_icon("freq_page")

        with ui.row().classes("items-center gap-2"):
            start_in = ui.input(label("data.start")).props("dense").classes("w-48 font-mono")
            end_in = ui.input(label("data.end")).props("dense").classes("w-48 font-mono")
            with ui.button(icon="schedule").props("flat dense").tooltip(label("data.presets")):
                with ui.menu():
                    for p in PRESETS:
                        ui.menu_item(label(f"preset.{p}"), on_click=lambda p=p: apply_preset(p))
            tz = ui.toggle({False: label("data.utc"), True: label("data.local")}, value=state.use_local_time) \
                .props("dense no-caps")
            units = ui.toggle({"counts": "counts", "m/s": "m/s"}, value="counts").props("dense no-caps")
            if not has_response:
                units.tooltip(label("freq.units_need_response"))
            help_icon("freq_units")

        with ui.row().classes("items-center gap-3"):
            go = ui.button(label("freq.find"), icon="search").props("no-caps color=accent").mark("freq-find")
            progress = ui.linear_progress(value=0, show_value=False).classes("w-48")
            progress.set_visibility(False)
            note = ui.label(label("freq.hint")).classes("text-sm text-grey-7")

        result_box = ui.column().classes("w-full gap-2")

        def write_fields() -> None:
            start_in.value = timeutil.to_text(sel[0], tz.value)
            end_in.value = timeutil.to_text(sel[1], tz.value)

        def apply_preset(name: str) -> None:
            sel[0], sel[1] = timeutil.preset_range(name, UTCDateTime(), tz.value)
            write_fields()

        def read_fields() -> bool:
            try:
                a = timeutil.from_text(start_in.value, tz.value)
                b = timeutil.from_text(end_in.value, tz.value)
            except ValueError:
                ui.notify(label("data.bad_time"), type="warning")
                return False
            if b <= a:
                ui.notify(label("freq.bad_range"), type="warning")
                return False
            if b - a > MAX_DAYS * 86400:
                ui.notify(label("freq.too_long").format(days=MAX_DAYS), type="warning")
                return False
            sel[0], sel[1] = a, b
            return True

        def on_tz(_=None) -> None:
            state.set_use_local_time(tz.value)
            write_fields()

        tz.on_value_change(on_tz)

        async def find() -> None:
            if not read_fields():
                return
            inventory = None
            if units.value == "m/s":
                try:
                    inventory = await run.io_bound(inventory_for, state, net, sta)
                except Exception as exc:
                    ui.notify(f"{label('freq.no_response')}: {exc}", type="negative", multi_line=True)
                    return
            s = Selection(net, sta, loc, sel[0], sel[1], channels=channels, units=units.value)
            go.disable()
            progress.set_visibility(True)
            note.text = label("freq.working")
            try:
                a = await run.io_bound(analyse, state.store, s, inventory)
            except Exception as exc:
                ui.notify(str(exc), type="negative", multi_line=True)
                return
            finally:
                go.enable()
                progress.set_visibility(False)
            note.text = ""
            result["analysis"] = a
            show(a)

        go.on_click(find)

        def show(a: Analysis) -> None:
            result_box.clear()
            with result_box:
                ui.label(summary_text(a)).classes("text-base font-bold")
                if not a.channels:
                    return
                skipped = ", ".join(f"{n} {k}" for k, n in a.skipped.items() if n)
                ui.label(label("freq.details").format(hours=f"{a.hours_used:.1f}", block=a.block_s // 60,
                                                      res=f"{a.resolution_hz:.3f}")
                         + (f" · {label('freq.skipped')}: {skipped}" if skipped else "")).classes("text-sm text-grey-7")
                if a.channels and min(r.n_blocks for r in a.channels.values()) < 5:
                    ui.label(label("freq.few_blocks")).classes("text-sm text-orange-9")
                log = ui.toggle({False: label("freq.linear"), True: label("freq.log")}, value=False) \
                    .props("dense no-caps")
                chart = ui.echart(frequency_options(a.channels, a.units)).classes("w-full").style("height: 42vh")

                def redraw(_=None) -> None:
                    chart.options.clear()
                    chart.options.update(frequency_options(a.channels, a.units, log.value))
                    chart.update()

                log.on_value_change(redraw)
                columns = [{"name": k, "label": label(f"freq.col_{k}"), "field": k, "align": "left"}
                           for k in ("channel", "freq", "contrast", "occurrence", "spread", "stable")]
                ui.table(columns=columns, rows=peak_rows(a), row_key="freq").props("dense flat").classes("max-w-3xl")
                with ui.row().classes("gap-2"):
                    for kind, text in (("png", "PNG"), ("pdf", "PDF"), ("csv", label("freq.peaks_csv")),
                                       ("spectra", label("freq.spectra_csv"))):
                        ui.button(text, icon="download", on_click=lambda k=kind: export(k)).props("flat dense no-caps")

        async def export(kind: str) -> None:
            a = result["analysis"]
            if a is None:
                return
            stem = f"{net}.{sta}_frequencies_{a.start.strftime('%Y%m%dT%H%M%S')}_{a.end.strftime('%Y%m%dT%H%M%S')}"
            out = Path(tempfile.mkdtemp()) / (f"{stem}_spectra.csv" if kind == "spectra" else f"{stem}.{kind}")
            writers = {"png": lambda: write_figure(a, out), "pdf": lambda: write_figure(a, out),
                       "csv": lambda: write_peaks_csv(a, out), "spectra": lambda: write_spectra_csv(a, out)}
            await run.io_bound(writers[kind])
            ui.download.file(out, out.name)

        write_fields()
