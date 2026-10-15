"""Data page: choose a station and time range, download from the Shake or import a file, preview, export."""

from __future__ import annotations

import tempfile
from pathlib import Path
from urllib.parse import urlencode

from nicegui import run, ui
from obspy import UTCDateTime

from rs3d.app import timeutil
from rs3d.app.charts import (coverage_options, psd_options, set_event_areas, set_selection, set_stream_data,
                             spectrogram_options, waveform_options)
from rs3d.app.state import CHANNELS, AppState
from rs3d.app.strings import label
from rs3d.app.widgets import frame, help_icon
from rs3d.core import archive
from rs3d.core.codegen import generate
from rs3d.core.coverage import State, coverage
from rs3d.core.events_scan import days_between, scan_day
from rs3d.core.export import load_processed, write_csv, write_mseed, write_plot
from rs3d.core.health import health
from rs3d.core.models import Device, Selection
from rs3d.core.response import cache_path, cached_inventory, get_inventory
from rs3d.core.spectro import psd_summary, spectrogram, window_for

ZOOMS = ("week", "day", "hour")
MAX_IMPORT_BYTES = 2_000_000_000


def files_needed(remote: set, local_days_by_channel: dict, start: UTCDateTime, end: UTCDateTime,
                 channels: tuple[str, ...]) -> int:
    return sum(len(archive.days_to_fetch(remote, local_days_by_channel.get(ch, set()), start.date,
                                         (end - 1e-6).date)) for ch in channels)


def scan_dates(start: UTCDateTime, end: UTCDateTime, available: set) -> list:
    """Days of the selection that exist locally, ascending (an end exactly at midnight excludes the next day)."""
    return [d for d in days_between(start.date, (end - 1e-6).date) if d in available]


def station_key(net: str, sta: str, loc: str) -> str:
    return f"{net}.{sta}.{loc}"


def station_choices(state: AppState, device: Device | None) -> list[str]:
    """Stations with data on this laptop, plus the current Shake (first)."""
    keys = [station_key(*s) for s in state.store.stations()]
    if device is not None and device.station:
        dev_key = station_key(device.network, device.station, device.location)
        if dev_key in keys:
            keys.remove(dev_key)
        keys.insert(0, dev_key)
    return keys


def default_range(state: AppState, net: str, sta: str, loc: str, channel: str) -> list[UTCDateTime]:
    """Last hour of the newest local data (imported files are usually not 'now')."""
    newest = max(state.store.days(net, sta, loc, channel))
    day_end = UTCDateTime(newest.year, newest.month, newest.day) + 86400
    segs = coverage(state.store, net, sta, loc, channel, day_end - 86400, day_end, set())
    end = max((s.end for s in segs if s.state is State.LOCAL), default=day_end)
    return [UTCDateTime(int(end.timestamp)) - 3600, UTCDateTime(int(end.timestamp))]


def register(state: AppState) -> None:
    @ui.page("/data")
    def data_page(start: str | None = None, end: str | None = None, station: str | None = None) -> None:
        device = frame(state, "data")
        choices = station_choices(state, device)

        async def on_import(e) -> None:
            target = Path(tempfile.mkdtemp()) / Path(e.file.name).name
            await e.file.save(target)
            try:
                written = await run.io_bound(state.store.import_file, target)
            except Exception as exc:
                ui.notify(f"{e.file.name}: {exc}", type="negative", multi_line=True)
                return
            if not written:
                ui.notify(f"{e.file.name}: {label('data.nothing')}", type="warning")
                return
            parts = written[0].name.split(".")
            key = station_key(parts[0], parts[1], parts[2])
            ui.notify(f"{label('data.imported')}: {key} ({len(written)})", type="positive")
            ui.navigate.to("/data?" + urlencode({"station": key}))

        with ui.row().classes("items-center gap-2"):
            remembered = state.data_prefs["station"]
            picker = ui.select(choices, value=station if station in choices else
                               (remembered if remembered in choices else (choices[0] if choices else None)),
                               label=label("data.station")).props("dense").classes("w-56")
            uploader = ui.upload(auto_upload=True, on_upload=on_import, max_file_size=MAX_IMPORT_BYTES) \
                .props('accept=".mseed,.msd,.miniseed,.ms"').classes("hidden")
            ui.button(label("data.import"), icon="upload_file",
                      on_click=lambda: uploader.run_method("pickFiles")).props("flat dense no-caps")
            help_icon("import")
        if not choices:
            ui.label(label("data.empty")).classes("text-grey-7")
            return

        net, sta, loc = picker.value.split(".")
        is_device = device is not None and (device.network, device.station, device.location) == (net, sta, loc)
        channels = tuple(state.store.channels(net, sta, loc))
        if is_device:
            channels = tuple(dict.fromkeys(CHANNELS + channels))
        def on_station(e) -> None:
            state.set_data_prefs(station=e.value)
            ui.navigate.to("/data?" + urlencode({"station": e.value}))

        picker.on_value_change(on_station)

        if start and end:
            sel = [UTCDateTime(float(start)), UTCDateTime(float(end))]
        elif is_device or not channels:
            sel = list(timeutil.preset_range("last_hour", UTCDateTime(), state.use_local_time))
        else:
            sel = default_range(state, net, sta, loc, channels[0])
        if not channels:
            ui.label(label("data.nothing")).classes("text-grey-7")
            return
        ctx = {"zoom": "day", "view": timeutil.view_range("day", sel[1]), "remote": set(), "stream": None}

        # ------------------------------------------------------------ 1. time range
        with ui.row().classes("items-center gap-2"):
            start_in = ui.input(label("data.start")).props("dense").classes("w-48 font-mono")
            end_in = ui.input(label("data.end")).props("dense").classes("w-48 font-mono")
            with ui.button(icon="schedule").props("flat dense").tooltip(label("data.presets")):
                with ui.menu():
                    for p in timeutil.PRESETS:
                        ui.menu_item(label(f"preset.{p}"), on_click=lambda p=p: apply_preset(p))
            tz = ui.toggle({False: label("data.utc"), True: label("data.local")}, value=state.use_local_time) \
                .props("dense no-caps")
            help_icon("timezone")
            duration = ui.label("").classes("text-sm text-grey-7")

        with ui.row().classes("items-center gap-2 w-full"):
            ui.toggle({z: label(f"data.{z}") for z in ZOOMS}, value="day",
                      on_change=lambda e: set_zoom(e.value)).props("dense no-caps")
            ui.button(icon="chevron_left", on_click=lambda: move(-1)).props("flat dense round")
            view_label = ui.label("").classes("font-mono text-sm")
            ui.button(icon="chevron_right", on_click=lambda: move(1)).props("flat dense round")
            help_icon("coverage")
        bar = ui.echart(coverage_options(ctx["view"], [], tuple(sel), use_utc=not state.use_local_time)) \
            .classes("w-full").style("height: 90px")

        with ui.row().classes("items-center gap-2"):
            needed = ui.label("").classes("text-sm")
            help_icon("files_needed")

        # ------------------------------------------------------------ 2. processing
        with ui.row().classes("items-center gap-4"):
            ch_boxes = {ch: ui.checkbox(ch, value=True) for ch in channels}
            prefs = state.data_prefs
            flt = ui.switch(label("data.filter"), value=prefs["filter"])
            fmin = ui.number(value=prefs["fmin"], min=0.01, step=0.5, format="%.2f").props("dense").classes("w-20")
            fmax = ui.number(value=prefs["fmax"], min=0.02, step=0.5, format="%.2f").props("dense").classes("w-20")
            ui.label("Hz")
            with ui.row().classes("items-center gap-1"):
                units = ui.toggle(["counts", "m/s"], value=prefs["units"]).props("dense no-caps")
                help_icon("units")
            go = ui.button(label("action.download_preview" if is_device else "action.preview"),
                           icon="download" if is_device else "visibility").props("unelevated")
            rescan = ui.button(label("events.rescan"), icon="radar").props("flat dense no-caps")

        # ------------------------------------------------------------ 3. preview / 4. export
        progress = ui.label(label("data.hint")).classes("text-sm text-grey-7")
        status = {"text": label("data.hint")}  # written by the worker thread, shown by a UI timer
        ui.timer(0.3, lambda: setattr(progress, "text", status["text"]))
        preview = ui.echart(waveform_options(channels, use_utc=not state.use_local_time)) \
            .classes("w-full").style("height: 48vh")
        with ui.row().classes("items-center gap-2"):
            ui.label(label("data.export")).classes("font-bold")
            export_buttons = [
                ui.button("miniSEED", on_click=lambda: export("mseed")).props("flat dense no-caps"),
                ui.button("CSV", on_click=lambda: export("csv")).props("flat dense no-caps"),
                ui.button("PNG", on_click=lambda: export("png")).props("flat dense no-caps"),
                ui.button("PDF", on_click=lambda: export("pdf")).props("flat dense no-caps"),
                ui.button("</> " + label("data.code"), on_click=lambda: show_code()).props("flat dense no-caps"),
            ]
            help_icon("code")
        for b in export_buttons:
            b.disable()

        ui.label(label("data.health")).classes("font-bold")
        health_label = ui.label("—").classes("text-sm")
        health_gaps = ui.column().classes("gap-0 font-mono text-sm")
        with ui.row().classes("items-center gap-2"):
            ui.label(label("data.spectrogram")).classes("font-bold")
            spec_channel = ui.select(list(channels), value=channels[0]).props("dense").classes("w-24")
        spec_chart = ui.echart({"series": []}).classes("w-full").style("height: 36vh")
        ui.label(label("data.psd")).classes("font-bold")
        psd_chart = ui.echart({"series": []}).classes("w-full").style("height: 28vh")

        # ------------------------------------------------------------ helpers
        def selection() -> Selection:
            chans = tuple(ch for ch, box in ch_boxes.items() if box.value) or channels
            band = (float(fmin.value), float(fmax.value)) if flt.value else None
            return Selection(net, sta, loc, sel[0], sel[1], channels=chans, filter=band, units=units.value)

        def write_fields() -> None:
            start_in.value = timeutil.to_text(sel[0], tz.value)
            end_in.value = timeutil.to_text(sel[1], tz.value)
            seconds = int(sel[1] - sel[0])
            duration.text = f"{seconds // 3600} h {seconds % 3600 // 60:02d} m {seconds % 60:02d} s"
            local = {ch: state.store.days(net, sta, loc, ch) for ch in channels}
            n = files_needed(ctx["remote"], local, sel[0], sel[1], selection().channels)
            needed.text = f"{label('data.files_needed')}: {n}"

        def redraw_bar() -> None:
            view = ctx["view"]
            view_label.text = f"{timeutil.to_text(view[0], tz.value)[:16]} → {timeutil.to_text(view[1], tz.value)[:16]}"
            segs = coverage(state.store, net, sta, loc, channels[0], view[0], view[1], ctx["remote"])
            bar.options.clear()
            bar.options.update(coverage_options(view, segs, tuple(sel), now=UTCDateTime(), use_utc=not tz.value))
            bar.update()

        def mark_events(s: Selection) -> None:
            found = state.events.events_between(s.start.timestamp, s.end.timestamp)
            set_event_areas(preview.options, [(e.start, e.end) for e in found])
            preview.update()

        async def scan_selection(s: Selection) -> None:
            """Detect events on the selection's stored days with the current settings, then mark them."""
            cfg = state.event_settings
            if not cfg.enabled:
                mark_events(s)
                return
            days = scan_dates(s.start, s.end, state.store.days(net, sta, loc, cfg.channel))
            status["text"] = label("events.scanning")
            total = 0
            for day in days:
                total += await run.io_bound(scan_day, state.store, state.events, cfg, net, sta, loc, day)
            status["text"] = label("events.found").format(n=total)
            mark_events(s)

        async def on_rescan() -> None:
            rescan.disable()
            try:
                await scan_selection(selection())
            except Exception as exc:
                ui.notify(str(exc), type="negative", multi_line=True)
            finally:
                rescan.enable()

        rescan.on_click(on_rescan)

        def set_range(a: UTCDateTime, b: UTCDateTime) -> None:
            if b <= a:
                return
            sel[0], sel[1] = a, b
            if not (ctx["view"][0] <= a and b <= ctx["view"][1]):
                ctx["view"] = timeutil.view_range(ctx["zoom"], b)
                redraw_bar()
            else:
                set_selection(bar.options, (a, b))
                bar.update()
            write_fields()

        def apply_preset(name: str) -> None:
            a, b = timeutil.preset_range(name, UTCDateTime(), tz.value)
            if name == "last_7_days":
                ctx["zoom"] = "week"
            set_range(a, b)

        def on_field(_=None) -> None:
            try:
                a = timeutil.from_text(start_in.value, tz.value)
                b = timeutil.from_text(end_in.value, tz.value)
            except ValueError:
                ui.notify(label("data.bad_time"), type="warning")
                return
            set_range(a, b)

        def on_zoom(e) -> None:
            args = e.args or {}
            batch = args.get("batch") or [args]
            a_pct, b_pct = batch[0].get("start"), batch[0].get("end")
            if a_pct is None or b_pct is None:
                return
            a = timeutil.percent_to_time(ctx["view"], a_pct)
            b = timeutil.percent_to_time(ctx["view"], b_pct)
            if b > a:
                sel[0], sel[1] = a, b
                write_fields()

        def set_zoom(level: str) -> None:
            ctx["zoom"] = level
            ctx["view"] = timeutil.view_range(level, sel[1])
            redraw_bar()

        def move(direction: int) -> None:
            ctx["view"] = timeutil.view_range(ctx["zoom"],
                                              timeutil.shift_view(ctx["zoom"], ctx["view"][0], direction))
            redraw_bar()

        def draw_health(st, s: Selection) -> None:
            ctx["health"] = (st, s)
            h = health(st, s.start, s.end)
            gap_text = label("data.no_gaps") if not h.gaps else f"{len(h.gaps)} {label('data.gaps')}"
            health_label.text = f"{h.completeness * 100:.2f} % {label('data.completeness')} · {gap_text}"
            health_gaps.clear()
            with health_gaps:
                for a, b in h.gaps[:50]:
                    ui.label(f"{timeutil.to_text(a, tz.value)} → {timeutil.to_text(b, tz.value)}  ({int(b - a)} s)")
                if len(h.gaps) > 50:
                    ui.label(f"… +{len(h.gaps) - 50}")

        def draw_spectrogram() -> None:
            st = ctx["stream"]
            traces = st.select(channel=spec_channel.value).copy() if st is not None else []
            if not len(traces):
                spec_chart.options.clear()
                spec_chart.options.update({"series": []})
                spec_chart.update()
                psd_chart.options.clear()
                psd_chart.options.update({"series": []})
                psd_chart.update()
                return
            traces.merge(method=0)  # one masked trace; gaps become masked samples
            tr = traces[0]
            times, freqs, power = spectrogram(tr, window_for(tr.stats.endtime - tr.stats.starttime))
            spec_chart.options.clear()
            spec_chart.options.update(spectrogram_options(times, freqs, power, use_utc=not tz.value))
            spec_chart.update()
            psd_chart.options.clear()
            psd_chart.options.update(psd_options(*psd_summary(freqs, power)))
            psd_chart.update()

        spec_channel.on_value_change(lambda _: draw_spectrogram())

        def save_prefs(_=None) -> None:
            state.set_data_prefs(units=units.value, filter=bool(flt.value),
                                 fmin=float(fmin.value or 1.0), fmax=float(fmax.value or 10.0))

        for control in (units, flt, fmin, fmax):
            control.on_value_change(save_prefs)

        def on_tz(_=None) -> None:
            state.set_use_local_time(tz.value)
            draw_spectrogram()
            if ctx.get("health"):
                draw_health(*ctx["health"])
            write_fields()
            redraw_bar()
            preview.options["useUTC"] = not tz.value
            preview.update()

        start_in.on("keydown.enter", on_field)
        start_in.on("blur", on_field)
        end_in.on("keydown.enter", on_field)
        end_in.on("blur", on_field)
        tz.on_value_change(on_tz)
        bar.on("chart:datazoom", on_zoom)
        for box in ch_boxes.values():
            box.on_value_change(lambda _: write_fields())

        async def load_remote_days() -> None:
            def fetch() -> set:
                with state.shell(device) as sh:
                    return archive.list_remote_days(sh.sftp(), net, sta, loc, channels[0])
            try:
                ctx["remote"] = await run.io_bound(fetch) or set()
            except Exception:
                ctx["remote"] = set()
            write_fields()
            redraw_bar()

        async def download_and_preview() -> None:
            s = selection()
            go.disable()
            try:
                def work():
                    if is_device:
                        try:
                            with state.shell(device) as sh:
                                archive.sync(sh.sftp(), state.store, net, sta, loc, s.channels,
                                             s.start.date, (s.end - 1e-6).date,
                                             progress=lambda i, n, what: status.update(
                                                 text=f"{label('data.downloading')} {i}/{n}: {what}"))
                        except Exception as exc:  # offline: use what is already on the laptop
                            status["text"] = str(exc)
                    inv = None
                    if s.units == "m/s":
                        inv = cached_inventory(state.paths.response, net, sta) or \
                            get_inventory(state.paths.response, net, sta)
                    return load_processed(state.store, s, inv)

                st = await run.io_bound(work)
                if st is None:  # client went away
                    return
                ctx["stream"] = st
                set_stream_data(preview.options, st)
                preview.update()
                draw_spectrogram()
                draw_health(st, s)
                status["text"] = "" if len(st) else label("data.nothing")
                for b in export_buttons:
                    b.enable() if len(st) else b.disable()
                redraw_bar()
                write_fields()
                if len(st):
                    await scan_selection(s)
            except Exception as exc:
                ui.notify(str(exc), type="negative", multi_line=True)
            finally:
                go.enable()

        go.on_click(download_and_preview)

        def base_name(s: Selection) -> str:
            return f"{s.network}.{s.station}_{s.start.strftime('%Y%m%dT%H%M%S')}_{s.end.strftime('%Y%m%dT%H%M%S')}"

        async def export(kind: str) -> None:
            st, s = ctx["stream"], selection()
            if st is None:
                return
            out = Path(tempfile.mkdtemp()) / f"{base_name(s)}.{kind}"
            writers = {"mseed": lambda: write_mseed(st, out), "csv": lambda: write_csv(st, out, s.channels),
                       "png": lambda: write_plot(st, out), "pdf": lambda: write_plot(st, out)}
            await run.io_bound(writers[kind])
            ui.download.file(out, out.name)

        def show_code() -> None:
            s = selection()
            inv_path = cache_path(state.paths.response, net, sta) if s.units == "m/s" else None
            code = generate(s, state.paths.sds, inv_path)
            with ui.dialog() as dialog, ui.card().classes("w-full max-w-3xl"):
                ui.code(code, language="python").classes("w-full")
                with ui.row():
                    ui.button(label("action.save_py"),
                              on_click=lambda: ui.download.content(code, f"{base_name(s)}.py")).props("flat")
                    ui.button(label("action.close"), on_click=dialog.close).props("flat")
            dialog.open()

        write_fields()
        redraw_bar()
        if is_device:
            ui.timer(0.1, load_remote_days, once=True)
