# RS3D live helicorder: design

Date: 2026-10-15. Status: draft for review. Branch `feat/rs3d-live-helicorder` (stacked on `feat/rs3d-clock-sync`, MR !3).

## Goal

The Live page shows only the last 10 minutes. The user wants a drum-recorder view of the whole current day on the same
page: 48 rows of 30 minutes, the current row growing as data arrives, events shaded, and already full when the app starts.

## Decisions (agreed in chat)

- A **Waveform | Helicorder** toggle on the Live page (option 1 of three offered).
- History at start-up comes from the Shake's own archive (option B): the app fetches today's day file over SFTP.
- Counts only, no band-pass, no m/s. Each row is shown without its DC offset (as on the Helicorder page).
- No click-to-zoom on this view; a button opens the same day on the Helicorder page.
- If the Shake is unreachable at start-up, the view starts empty and fills from the live stream.

## 1. Data: `core/day_trace.py` (new, no UI imports)

`DayTrace` keeps, per channel, one (min, max) pair per second of one UTC day: two float arrays of 86 400 values, NaN
meaning "no data" (about 4 MB for three channels). Thread-safe (a lock, like `RingBuffer`).

- `DayTrace(day: date)`; `day` is the UTC day it covers.
- `add(tr: Trace)`: folds a trace into the seconds it covers (per-second min and max; a second already filled is
  extended by min/max, not replaced). Samples outside `day` are ignored.
- `replace_from(st: Stream)`: fills seconds from archive data. Only seconds that live data has not yet filled are
  written, so live data wins an overlap.
- `rows(channel, row_minutes=30) -> list[Row]`: the 48 `Row` objects the Helicorder page already draws. Each row has
  2 points per second (min and max, 3 600 points per row, close to the existing `POINTS_PER_ROW`); an empty second becomes a NaN
  break; the row median is subtracted. `Row` and `scale_for` come from `core/helicorder.py` unchanged.
- `start` property: the first epoch second of the day, for the click-free layout and for event shading.

`AppState` owns one `DayTrace` per Shake. A trace that belongs to the next UTC day replaces the accumulator with a fresh
one for the new day (midnight rollover); the old day is complete on the Shake and is on the Helicorder page.

## 2. Preload: `core/preload.py` (new)

`preload_today(sftp, store, device, day_trace, now)`: for each live channel, `archive.download_day` of today's file into
the local store (it is the same file the Data page downloads, so nothing new is written elsewhere), then
`store.load` for the day and `day_trace.replace_from`. Runs in a worker thread started by `AppState.start_current`
and must never raise into the UI: any SFTP, SSH or parse error is logged and leaves the accumulator as it is.

- The archive file grows while the Shake records, so a copy can end in a truncated record. A record ObsPy cannot read is
  skipped; what was read is used.
- If the live stream delivers data while the preload runs, both write into the same `DayTrace`; the live-wins rule above
  makes the order irrelevant.

Detector warm-up (the 30 s of silence after start) is **not** part of this version. The archive normally ends minutes
before the app starts, and the detector deliberately resets across a gap, so a replay would not reliably arm it.
A SeedLink back-fill (`begin_time`) would, and is noted as a follow-up.

## 3. UI: Live page

- A toggle **Waveform | Helicorder** after the window buttons; the choice is remembered in `data_prefs`-style state for
  the session only (not saved to settings).
- Helicorder mode hides the window toggle, filter and pause controls (they do not apply) and shows a channel picker
  (channels the stream has delivered, default EHZ), the scale selector (0.5× to 8×, same values as the Helicorder page),
  and an **Open on Helicorder page** button (`/helicorder?station=…&day=<today>&channel=…`).
- The chart is built with `helicorder_options(rows, scale_for(rows, factor))` and `set_helicorder_events` with the
  spans from `state.events.events_between(day_start, day_start + 86400)` for the channel plus the open event
  (`live_spans` already handles the open event). Height `helicorder_height_px(48)`.
- Refresh every 5 s (one row grows by about 1/360 of its width per 5 s; 0.25 s would waste CPU building 48 series).
  Switching to the mode renders at once.
- The row labels follow `state.use_local_time` the same way the Helicorder page does.

## 4. Edge cases

- No data yet at all: the chart is empty and a line says so (existing `live.waiting` text).
- A gap (Shake offline, wrong clock): the seconds stay NaN; the line breaks.
- Clock jump (Shake time wrong): data lands on the day its timestamps say; a trace from another day than today's is
  ignored unless it is later than today's end (rollover). A trace older than today is ignored.
- Two Shakes configured: one `DayTrace` per Shake, the page uses the current device.
- Memory: 3 channels × 2 × 86 400 × 8 bytes per Shake.

## 5. Testing

- `DayTrace`: add a trace and read min/max per second; two traces in one second extend it; a gap gives NaN; a trace on
  another day is ignored or rolls over; `replace_from` never overwrites a live second; `rows` shape (48 rows, NaN
  breaks, median removed) and agreement with `build_rows` on the same data after the min/max reduction.
- `preload_today` with a fake SFTP: fills the accumulator; an SFTP error leaves it unchanged and does not raise; a
  truncated file keeps the readable part.
- Live page helpers (pure functions, as for `banner_state`): the options builder for the helicorder mode.
- One `device` test (not run by the agent): start the app against the real Shake, expect a filled helicorder.
- CHANGELOG line, Guide paragraph, (?) help text for the toggle.
