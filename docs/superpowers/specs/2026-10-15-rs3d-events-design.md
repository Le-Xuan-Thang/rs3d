# RS3D event detection and alerts: design

Date: 2026-10-15. Status: draft for review.

## Goal

When the ground shakes above a threshold while RS3D is running, show an on-screen alert and save the event. The same
detection runs over downloaded days, so events are marked on the Data page and on the helicorder. The behaviour matches
the `alert` plugin of rsudp (STA/LTA trigger), with the same default values the user already runs in rsudp.

## Scope

In scope: STA/LTA detector, event log, on-screen banner on the Live page, event list, automatic scan of downloaded days,
manual rescan, event markers on the Data page and the helicorder, Settings card.

Out of scope for now (planned later, shown as "coming soon" in Settings): sound, desktop/browser notification,
email/Telegram. The detector exposes an `on_event` callback so these become extra listeners without touching detection.

## 1. Detection core: `core/events.py`

No UI imports.

- `EventSettings` (dataclass): `enabled=True`, `channel="EHZ"`, `sta=6.0`, `lta=30.0`, `on=3.95`, `reset=0.9`,
  `highpass=0.8`, `lowpass=9.0`. Defaults are copied from the user's `~/.config/rsudp/rsudp_settings.json` (stock rsudp
  uses on 1.6, reset 1.1 and no band-pass).
- `Event` (dataclass): `start`, `end` (epoch seconds), `peak_ratio`, `peak_amplitude` (counts), `channel`, `source`
  (`"live"` or `"scan"`).
- `EventDetector(settings, on_event, on_start=None)`: fed with traces through `feed(trace)`. It band-passes, runs a
  recursive STA/LTA per sample, and applies the on/reset hysteresis.
  - An event starts when the ratio rises above `on` and ends when it falls below `reset`. `on_start(start, ratio)` fires
    at the start so the banner can appear at once; `on_event(Event)` fires at the end.
  - The detector stays silent while the LTA window fills (the first `lta` seconds after startup or after a data gap
    longer than one sample interval times a small tolerance), so warm-up never produces false events.
  - Only the configured channel is analysed. Other channels are ignored.
- `detect(trace, settings) -> list[Event]`: the same algorithm over a whole recorded trace. It shares its code with the
  live detector so both give the same result on the same data.

## 2. Storage: `core/events_store.py`

- `events.jsonl` in the data folder, one JSON object per line: the `Event` fields plus `source`.
- Appends are atomic per line. A corrupt line is skipped and counted, never fatal.
- Queries: `events_between(t0, t1)` and `latest(n)`.
- `replace_scan_events(day, events)`: removes `source == "scan"` events inside that day, then adds the new ones. Live
  events are never removed. Where a live and a scan event overlap in time, only the live one is listed.

## 3. Wiring

- `LiveStream` gets an optional `detector`. `_on_trace` passes each trace to `detector.feed` after the ring buffer, and
  a detector failure is caught and logged so it can never stop the stream.
- The detector is created at app start from the saved settings. Changing settings replaces it, which restarts warm-up
  (an event in progress when settings change is closed first).
- After a day is downloaded, the Data page runs `detect` on it in a worker thread and calls `replace_scan_events`. The
  day's row shows "scanning…" and then the event count.

## 4. UI

- **Live page**
  - Red banner while an event is active: "Event in progress, started 14:32:05, ratio 5.2".
  - When it ends the banner changes to "Event ended, duration 12 s, peak …" and stays until dismissed.
  - The chart shades the event span.
  - A short list of the latest events sits below the chart.
- **Data page.** Event markers on the day view. A **Rescan** button re-runs detection with the current settings.
- **Helicorder.** Events are marked on their rows. Clicking one opens the existing detail view for that time range.
- **Settings, "Events" card.** On/off switch, channel, STA, LTA, on, reset, band-pass, each with a (?) help icon, and a
  reset-to-defaults button. A greyed line reads "Sound / desktop notification / email: coming soon". Changes apply to
  the live detector immediately and do not re-scan old data.
- Strings go through `app/strings.py` (English first, like the rest of the app).

## 5. Error handling

- Invalid settings (LTA not larger than STA, reset not below on, band-pass outside 0 to Nyquist) are rejected in the
  Settings form with a message. The previous values stay active.
- Gaps in the live data restart warm-up. An event open at the gap is closed at the last sample before it.
- If `events.jsonl` cannot be written, the banner and in-memory list still work and the Status page shows a warning.
- If the configured channel is missing from the data, the detector idles and the Events card says so.

## 6. Testing

- Unit tests for `core/events.py` on synthetic traces: noise only gives no event; a burst gives exactly one event with
  the right start and end; a burst inside the warm-up window is ignored; a gap restarts warm-up; band-pass removes a
  burst outside the band; live feed in small chunks and `detect` on the whole trace give the same events.
- Unit tests for the store: round trip, corrupt line skipped, `replace_scan_events` keeps live events.
- Test that a detector exception does not stop `LiveStream`.
- One check on the real file `rsudp_out/data/fdsnws.mseed` (AM.RF7B3). Live behaviour with the real Shake stays on
  the existing "Pending, needs the Shake on the cable" list.
- UI pieces (banner text, settings validation) as pure functions, tested like `status_text` and `band_for` in
  `app/pages/live.py`.
