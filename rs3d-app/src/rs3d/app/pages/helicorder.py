"""Helicorder page: one channel of one UTC day as 48 rows of 30 minutes; a click picks a time."""

from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import urlencode

from nicegui import run, ui
from obspy import UTCDateTime

from rs3d.app.charts import helicorder_height_px, helicorder_options
from rs3d.app.detail import DetailContext, DetailPanel, inventory_for
from rs3d.app.latest import LatestOnly
from rs3d.app.pages.data import station_choices
from rs3d.app.state import AppState
from rs3d.app.strings import label
from rs3d.app.widgets import frame
from rs3d.core.helicorder import ROW_MINUTES, build_rows, click_to_time, load_day, scale_for

SCALES = {0.5: "0.5×", 1.0: "1×", 2.0: "2×", 4.0: "4×", 8.0: "8×"}


def parse_day(text: str | None, fallback: date) -> date:
    try:
        return date.fromisoformat(text) if text else fallback
    except ValueError:
        return fallback


def register(state: AppState) -> None:
    @ui.page("/helicorder")
    def helicorder_page(station: str | None = None, day: str | None = None, channel: str | None = None) -> None:
        device = frame(state, "helicorder")
        choices = station_choices(state, device)
        if not choices:
            ui.label(label("data.empty")).classes("text-grey-7")
            return
        remembered = state.data_prefs["station"]
        key = station if station in choices else (remembered if remembered in choices else choices[0])
        net, sta, loc = key.split(".")
        channels = tuple(state.store.channels(net, sta, loc))
        if not channels:  # a Shake is configured but nothing is downloaded yet
            ui.label(label("data.empty")).classes("text-grey-7")
            return
        ch = channel if channel in channels else channels[0]
        days = state.store.days(net, sta, loc, ch)
        # "day" is the day being asked for; "shown" is the day whose rows are on screen (clicks map against it)
        ctx = {"day": parse_day(day, max(days) if days else date.today())}
        ctx["shown"] = ctx["day"]
        latest = LatestOnly()

        def start_of(d: date) -> UTCDateTime:
            return UTCDateTime(d.year, d.month, d.day)

        with ui.row().classes("items-center gap-2"):
            picker = ui.select(choices, value=key, label=label("data.station")).props("dense").classes("w-56")
            chan = ui.select(list(channels), value=ch).props("dense").classes("w-24")
            ui.button(icon="chevron_left", on_click=lambda: move(-1)).props("flat dense round") \
                .mark("day-prev").tooltip(label("heli.previous_day"))
            day_label = ui.label(ctx["day"].isoformat()).classes("font-mono")
            ui.button(icon="chevron_right", on_click=lambda: move(1)).props("flat dense round") \
                .mark("day-next").tooltip(label("heli.next_day"))
            prefs = state.data_prefs
            units = ui.toggle(["counts", "m/s"], value=prefs["units"]).props("dense no-caps")
            flt = ui.switch(label("data.filter"), value=prefs["filter"])
            scale = ui.select(SCALES, value=1.0, label=label("heli.scale")).props("dense").classes("w-24")

        message = ui.label("").classes("text-grey-7")

        def detail_ctx() -> DetailContext:
            current = state.data_prefs
            band = (current["fmin"], current["fmax"]) if flt.value else None
            return DetailContext(net, sta, loc, chan.value, units.value, band, not state.use_local_time)

        detail = DetailPanel(state, detail_ctx)
        chart = ui.echart({"series": []}).classes("w-full")

        def navigate(**changes) -> None:
            args = {"station": picker.value, "channel": chan.value, "day": ctx["day"].isoformat(), **changes}
            ui.navigate.to("/helicorder?" + urlencode(args))

        picker.on_value_change(lambda e: navigate(station=e.value, channel=""))
        chan.on_value_change(lambda e: navigate(channel=e.value))

        async def refresh() -> None:
            token = latest.next()
            current = state.data_prefs
            band = (current["fmin"], current["fmax"]) if flt.value else None
            u = units.value
            wanted, channel_now = ctx["day"], chan.value  # snapshot: the worker thread must not see later changes

            def work():
                inv = inventory_for(state, net, sta) if u == "m/s" else None
                st = load_day(state.store, net, sta, loc, channel_now, wanted, u, band, inv)
                return build_rows(st, start_of(wanted))

            try:
                rows = await run.io_bound(work)
            except Exception as exc:  # e.g. no instrument response while offline
                if latest.is_current(token):
                    ui.notify(str(exc), type="negative", multi_line=True)
                    if u == "m/s":
                        units.value = "counts"  # triggers a new refresh in counts
                return
            if not latest.is_current(token):  # a newer load was started meanwhile: drop this result
                return
            ctx["shown"] = wanted
            day_label.text = wanted.isoformat()
            if not any(len(r.values) for r in rows):
                message.text = label("data.nothing")
                chart.options.clear()
                chart.options.update({"series": []})
                chart.style("height: 0px")
                chart.update()
                return
            message.text = ""
            chart.options.clear()
            chart.options.update(helicorder_options(rows, scale_for(rows, float(scale.value))))
            chart.style(f"height: {helicorder_height_px(len(rows))}px")
            chart.update()

        def move(direction: int) -> None:
            ctx["day"] = ctx["day"] + timedelta(days=direction)
            day_label.text = ctx["day"].isoformat()
            ui.timer(0.01, refresh, once=True)

        async def pick(t: UTCDateTime) -> None:
            await detail.open(t)

        async def on_click(e) -> None:
            if e.series_name != "click":
                return
            x_minutes, row = float(e.value[0]), int(round(float(e.value[1])))
            await pick(click_to_time(start_of(ctx["shown"]), ROW_MINUTES, row, x_minutes / ROW_MINUTES))

        chart.on_point_click(on_click)
        async def on_settings(_=None) -> None:
            await refresh()
            await detail.reload_if_open()  # the open detail view follows units and band-pass

        scale.on_value_change(lambda _: ui.timer(0.01, refresh, once=True))
        for control in (units, flt):
            control.on_value_change(lambda _: ui.timer(0.01, on_settings, once=True))
        ui.timer(0.1, refresh, once=True)
