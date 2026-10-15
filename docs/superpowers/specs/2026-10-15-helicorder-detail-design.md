# Helicorder and detail view — design

Date: 2026-10-15. Status: draft for review. Applies to `rs3d-app` (after tag `v0.1.0` plus the spectrogram, PSD,
health, saved-settings, live and browser-test work already on `main`).

This is sub-project 1 of 4. The others, each with its own spec: (2) live spectrogram, (3) alerts, (4) station view and
event check.

## Goal

Give the app the 24-hour view and click-to-zoom workflow of Raspberry Shake DataView, for the user's own Shake and
from the local archive only, so it works offline:

- a 24-hour **helicorder** (48 rows of 30 minutes);
- a click on any row opens a **detail view** of about 2 minutes with zoom, spectra, spectrogram and filter;
- a **Waveform Clipboard** that stacks waveform, spectrogram and spectrum and saves them as a PNG.

Not copied: no DataView code, logo or watermark. Everything is built on the app's own `core/` and `app/` layers.

## Success criteria

1. Opening **Helicorder** for a day with local data shows 48 rows, alternating colours, UTC hours on the left and local
   time on the right, with gaps as breaks. A full day renders in under 2 seconds on the laptop.
2. Clicking anywhere on a row opens a detail view centred on that time (±1 min by default). The detail window's centre is
   within 1 second of the clicked time (a pixel column is about 1.2 s on a 1500 px wide plot).
3. The detail view switches between waveform, spectra and spectrogram, zooms in and out, shifts earlier and later,
   and toggles the band-pass.
4. The clipboard dialog shows waveform, spectrogram and spectrum for the current window; the camera button downloads a
   non-blank PNG whose title states station, channel, UTC range, units and filter.
5. All of the above is covered by tests, including one real-browser test.

## Out of scope

Live "tail" updates of the helicorder; a multi-item clipboard; remote (Shake-only) days that are not downloaded yet
(the page tells the user to download them on the Data page); event markers (sub-project 4).

## Design

### Page and navigation

New page `/helicorder` with a sidebar entry. Controls: station, channel (default EHZ), date with previous and next
arrows (default: the newest day with local data), units (counts or m/s) and band-pass (shared with the Data page
through `state.data_prefs`). The detail view is a panel above the helicorder, hidden until the first click.
Strings go in `help/en.toml`.

### `core/helicorder.py` (new, no UI imports)

- `rows(store, net, sta, loc, channel, day, row_minutes=30, ...)` loads one channel of the day (plus the next day's
  first minutes when a row crosses midnight), applies units and band-pass with the existing `process()`, and returns 48
  `Row(start, offsets_s, values)` items.
- Each row is reduced to min/max pairs of about 3,000 points (the same method as `core/live._minmax_decimate`, reused
  or moved to a shared helper). Gaps stay NaN.
- `scale_for(rows, mode)` returns one amplitude per row-height shared by all rows. Auto mode is a robust percentile
  (99th of absolute values), so one large quake does not flatten the day. Modes: auto, plus fixed multipliers chosen
  from the Scale dropdown.
- `click_to_time(day_start, row_minutes, row_index, x_fraction)` is a pure function used by the page.

### `app/charts.py` (new builders, plain dicts)

- `helicorder_options(rows, scale, use_utc)` draws each row as a line offset by its row index on one grid. Rows alternate
  two colours. The left axis shows UTC hours, the right axis local hours. Each row also gets a transparent full-width
  band that acts as the click target.
- `detail_options(mode, ...)` for waveform, spectra (log-log amplitude) and spectrogram. Waveform reuses
  `waveform_options`; spectrogram reuses `spectrogram_options`.

### Click handling and spike

Step 1 of the plan is a spike to confirm that a NiceGUI `ui.echart` reports a click position inside a transparent band.
If it does not, the fallback is an event listener on the chart's ZRender layer that converts pixels with
`convertFromPixel`. The design above does not change; only how the click arrives does. If neither works, stop and
revisit this spec before building on it.

### Detail view

`core/spectro.py` gains `amplitude_spectrum(tr)` returning (freqs, amplitude) for one window, for the spectra mode.
The panel loads the window from the local archive (`store.load`, `process`) and exposes:

| Control | Behaviour |
|---|---|
| Fit | back to the originally clicked window |
| Zoom out / in | window ×2 / ×½ around its centre, then reload |
| ◀ ▶ | shift by half the window, then reload |
| Waveform / Spectra / Spectrogram | mutually exclusive panel modes |
| Filter | the helicorder page's Band-pass switch (one source of truth); the detail view reads it on every reload |
| Clipboard | opens the clipboard dialog |
| Close | hides the panel |

Mouse wheel and drag zoom and pan inside the loaded window (`dataZoom: inside`); the buttons reload when the user
leaves it. Time axes follow the existing UTC/Local toggle.

### Waveform Clipboard

A dialog with three stacked panels (waveform, spectrogram, spectrum) for the current detail window, a camera button
and a close button. The camera button calls `core/export.write_clipboard_png(st, path, title)`, which renders with
matplotlib on the server (same path as the existing PNG/PDF export) and triggers a download. One clipboard for the
current window only.

## Error handling

- No local data for the chosen day: the page shows the existing "No data" message and a link to the Data page.
- A click on a gap row (no samples in the window): the detail view says "No data in this window" and offers Fit.
- m/s without an instrument response: the same notification the Data page already shows; the page falls back to counts.
- Loading failures are shown with `ui.notify`, never as an unhandled exception.

## Testing

- Core (unit, synthetic data): row split, min/max reduction keeps peaks, NaN gaps, midnight crossing, shared scale
  ignores one outlier, `click_to_time`, `amplitude_spectrum` peaks at a known sine, clipboard PNG is written and not blank.
- Chart builders (unit): `helicorder_options` has 48 series, alternating colours, both axes; `detail_options` per mode.
- Page (NiceGUI simulation): Helicorder page renders; date arrows change the shown date; empty-day message.
- Real browser (`-m e2e`): import a 3-hour synthetic file, open `/helicorder`, click a row, detail view opens at the
  right time, switch to Spectrogram, open the clipboard, the camera button downloads a PNG that decodes and is not blank.
  As with the existing browser test, mutate the code once to confirm the test can fail.

## Open points

None blocking. The click spike is the one technical risk and has a defined fallback.
