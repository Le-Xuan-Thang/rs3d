# rs3d-app

Status, live view and data export for a Raspberry Shake 3D over Ethernet.

## Install and run

Needs Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run rs3d-app            # opens http://127.0.0.1:<port> in your browser
uv run rs3d-app --no-browser --port 8765
```

Without `--port` the app uses 8765, or any free port if that one is taken.

## What it does

| Page | Purpose |
|---|---|
| **Status** | Checks the connection to the Shake: network, SSH, data forwarding, clock, archive. |
| **Live** | Real-time EHZ/EHN/EHE waveforms over SeedLink (port 18000), optional band-pass. |
| **Helicorder** | 24-hour day view, one row per 30 minutes. Click a row to open a ~2 minute detail view (waveform, spectra, spectrogram, zoom, shift) and save a Waveform Clipboard picture. Uses the data already on the laptop. |
| **Data** | Pick a station and time range, download from the Shake's archive (or import a file), then view waveforms, spectrogram, noise spectrum (PSD) and data health (completeness, gaps). Export miniSEED, CSV, PNG, PDF, or a Python script that reproduces the processing. |
| **Guide**, **Settings** | Built-in help; device address, SSH user, password or key. |

## Using it without a Shake

Open **Data**, press **Import miniSEED** and choose a `.mseed` file. The station appears in the
station list and everything on the Data and Helicorder pages works on it, including the spectrogram.

## Using it with a Shake

1. Connect the Shake to the laptop over Ethernet.
2. **Settings**: enter the Shake's IP address, SSH user (default `myshake`) and password or key, then *Test connection*.
3. **Status** should show all checks green. **Live** and **Data** then work on the connected Shake.

Downloaded data is kept on the laptop in an SDS archive, so a range is only fetched from the Shake once.

## Development

```bash
uv run pytest              # unit and page tests, no device needed
uv run pytest -m e2e       # real-browser test (needs Google Chrome)
uv run pytest -m device    # extra tests that need a Shake on the network
```
