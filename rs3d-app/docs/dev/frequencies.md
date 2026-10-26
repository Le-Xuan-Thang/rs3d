# Frequencies page (developer notes)

The page finds stable spectral peaks in a time range of local data. It follows the method of the room-floor study
(`ChladniEQ_Room_Frequency_Energy_EN.tex`), simplified so a non-specialist can run it with two clicks.

## Where things are

| File | What |
|------|------|
| `src/rs3d/core/frequencies.py` | analysis: blocks, Welch PSD, median, peak picking, occurrence, `stable_lines` |
| `src/rs3d/core/frequencies_export.py` | peaks CSV, spectra CSV, PNG/PDF figure |
| `src/rs3d/app/pages/frequencies.py` | the page (`/frequencies`) |
| `src/rs3d/app/charts.py` `frequency_options` | the ECharts options |
| `src/rs3d/help/en.toml` | `[labels.freq]`, `[help.freq_page]`, `[help.freq_units]` |
| `tests/core/test_frequencies.py` | synthetic sines with known frequencies |

## Pipeline (`analyse`)

1. The selection is loaded one day at a time (`Store.load`), gaps merged as masks.
2. Blocks of `block_length(duration)` seconds (300–1800, about 20 blocks). A trailing block shorter than a third of
   the block (and under 60 s) is dropped.
3. Per block and channel: skip if it has a gap, is under 95 % full, or reaches 0.99 x 2^23 counts (counted in
   `Analysis.skipped`). Otherwise Welch PSD in dB (Hann, 50 % overlap, linear detrend, `nperseg` 8192 or the largest
   power of two with at least 4 segments per block). Units "m/s" remove the response first (pre-filter 0.2/0.4/40/45 Hz).
4. Median and P10/P90 over the blocks. Peaks of the median: prominence >= `PROMINENCE_DB` (6 dB), separation
   `MIN_SEPARATION_HZ`, inside `BAND` (0.7-35 Hz), top `TOP_PEAKS` (6).
5. For each peak: contrast against the sidebands 0.08-0.30 Hz away; occurrence = share of blocks with a >= 3 dB peak
   within max(0.05 Hz, 2 bins); P10/P90 of the matched frequencies.
6. `stable_lines`: peaks with occurrence >= `STABLE` (0.8), merged across channels within 0.15 Hz.

All the thresholds are module constants at the top of `frequencies.py`.

## Limits worth knowing

- A peak is a candidate, not a proven natural frequency (see the study's discussion: machinery, local slab modes).
- Occurrence percentages need enough blocks; the page warns under 5.
- Response removal is per block and slows long ranges; `MAX_DAYS` in the page caps a run at 14 days.
- No overlap between blocks and no weighting by block length.
- The orientation of N/E is whatever the Shake metadata says; it is not verified.

## Ideas not done

- Energy per band and the quiet-versus-active window comparison from the study.
- Time-frequency strip for the whole range.
- Progress bar driven by the `progress` callback of `analyse` (the page shows an indeterminate wait only).
- Jump from a Data page selection to this page with `?start=&end=` (the page already reads those parameters).
