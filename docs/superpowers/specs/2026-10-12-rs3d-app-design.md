# RS3D App – Design

- Date: 2026-10-12
- Project: NCREP-RaspberryShake
- Device: Raspberry Shake 3D `AM.R77A7.00` (EHZ, EHN, EHE · 100 Hz)
- Status: approved, English-first

## 1. Goal

A cross-platform app (Windows, macOS, Linux). A user plugs a laptop into a Shake with an Ethernet cable, opens the app, and can:

1. see the state of the Shake and of the connection at a glance, with how to fix problems;
2. watch the three channels live;
3. pick a time range, preview it, download the data and export it as files or as Python code.

### Out of scope for v1

- Changing settings on the Shake. The app is **read-only** towards the Shake; fixes are explained in (?) help.
- Connecting to the Shake over Wi-Fi. The app connects **over Ethernet only**.
- PGA/PGV, earthquake detection/alerts (rsudp), event dashboard.
- Packaged executables. v1 runs with `uvx rs3d-app`; packaging comes later (section 10).
- Languages other than English. See section 5.1.

## 2. Context and prerequisites

| Item | Decision |
|---|---|
| Shake clock | The Shake joins a Wi-Fi network with Internet and syncs its clock with its own `ntpd.service`. A USB GPS will be added later. The app does not serve time. |
| Before enabling Wi-Fi on the Shake | Turn off Data Forwarding and change the default `shakeme` password (done by following the Manual, outside the app). |
| Laptop ↔ Shake link | Ethernet cable, link-local addresses `169.254.0.0/16`. Several Shakes and several laptops may share one switch. |
| Users | Anyone who plugs a laptop in and runs the app. No central server. |
| Historical data source | The Shake writes daily miniSEED files to its SD card (`/opt/data/archive`, **to be verified**, section 11). |

## 3. Architecture

```
Shake (24/7, daily miniSEED, clock from Wi-Fi/NTP)
   │  Ethernet 169.254.x.x
   │    ├─ SeedLink TCP 18000 ──► live
   │    └─ SSH/SFTP TCP 22   ──► status + archive download
   ▼
Laptop (Win/macOS/Linux) ── rs3d-app ── browser / native window
```

- **All connections are outbound from the laptop**, so no firewall rule is needed on any OS.
- **One exception to "read-only":** the [Set IP] button changes the **laptop's** network settings (section 5.6), after user confirmation and an OS privilege prompt.

### Technology

| Concern | Library |
|---|---|
| UI | NiceGUI (browser now, native window later) |
| Charts | NiceGUI `ui.echart` |
| Seismic data | ObsPy (SeedLink, SDS, miniSEED, response, PNG/PDF plots) |
| SSH/SFTP | Paramiko |
| Device discovery | `zeroconf` (mDNS) |
| Password storage | `keyring` (Credential Manager / Keychain / Secret Service) |
| Data folders | `platformdirs` |

## 4. Components

```
src/rs3d/
├── core/                 # no UI dependency, testable on its own
│   ├── models.py         # Device, Check, Selection dataclasses
│   ├── devices.py        # device config read/write (config.toml) + keyring
│   ├── discovery.py      # mDNS + manual IP; identify a Shake by its SeedLink station code
│   ├── netcheck.py       # laptop link-local IP check; [Set IP] command per OS
│   ├── shell.py          # SSH session wrapper (paramiko): run read-only commands, SFTP
│   ├── status.py         # read-only checks → list[Check]
│   ├── live.py           # SeedLink stream → 10-minute ring buffer per channel, auto-reconnect
│   ├── store.py          # local SDS store: day-file paths, list days, load a Selection
│   ├── archive.py        # list / download Shake files (SFTP) into the local store
│   ├── coverage.py       # coverage: on Shake / downloaded / gap
│   ├── response.py       # obtain and cache instrument response (counts → m/s)
│   ├── export.py         # miniSEED, CSV, PNG, PDF
│   └── codegen.py        # ObsPy code matching the current Selection
├── app/
│   ├── main.py           # NiceGUI setup, layout A (left sidebar)
│   ├── help.py           # loads (?) texts from help/en.yaml
│   └── pages/            # status.py · live.py · data.py · guide.py · settings.py
├── help/en.yaml          # every explanatory text (tooltip + detail panel)
├── guide/en/             # Manual as Markdown for the Guide page
└── cli.py                # `rs3d-app` entry point
```

Interfaces:

- `Check(id, level: ok|warn|error|skipped, value: str, help_id: str, action: str | None)`. `status.py` returns data only; wording comes from `help/en.yaml` by `help_id`.
- `Device(name, host, seedlink_port=18000, ssh_user="myshake", key_path=None, network="AM", station="", location="00")`. The password is not in `Device`; it lives in the keyring under service `rs3d`, key `<host>`.
- `Selection(network, station, location, start, end, channels, filter: (fmin, fmax) | None, units: "counts"|"m/s")`. It holds stream codes rather than a `Device`, so data code never depends on connection settings. `export.py` and `codegen.py` take the same `Selection`, so exported files and generated code always agree.

## 5. User interface

### 5.1 Principles

- **Compact.** Screens show short labels and values only. All explanations sit behind a **(?)** icon: hover shows a 1–2 sentence tooltip; click opens a detail panel (cause, fix, commands).
- **Layout A.** Left sidebar with the device list (`● R77A7`, `+ Find Shake…`) and pages: Status · Live · Data · Guide · ⚙ Settings.
- **Language.** v1 is **English only**. All user-facing strings live in `help/en.yaml` and one `strings` table (no literals scattered in page code), so Vietnamese and Portuguese can be added later as `vi.yaml` / `pt.yaml` plus a Settings selector.
- **Time.** UTC by default, with a toggle to local time. Exported files and generated code always use UTC.

### 5.2 Status

One row per check: icon, label, value, (?), optional action button. Auto-refresh every 30 s plus a ↻ button.

| Check | OK | Warning / error |
|---|---|---|
| Laptop IP | `169.254.x.x` on a wired interface | error + [Set IP] |
| SeedLink | `host:18000` reachable | error |
| Channels | EHZ/EHN/EHE · 100 Hz | warning if a channel is missing |
| SSH | login works | error: wrong password / unreachable / SSH disabled |
| Clock | offset ≤ 100 ms with a sync source (`ntpq -p`) | warning > 100 ms; error > 1 s or no source |
| Storage | ≥ 10 % free | warning < 10 % |
| Archive | date range available on the Shake | warning if no archive found |
| Data Forwarding | OFF | warning when ON |
| Password | changed | warning when still the default |

Dependent checks show `skipped` instead of repeating an error:
- Laptop IP error → all other checks skipped.
- SSH error → Clock, Storage, Archive, Data Forwarding and Password skipped; SeedLink and Channels still run.

### 5.3 Live

- Three channels, window 30 s / 60 s / 5 min, filter on/off, pause.
- Chart refresh 4 times per second, data decimated to the chart width.
- [Save this segment] opens the Data page with Start/End filled in.
- On disconnect the chart shows "reconnecting". Missing data is left as a gap, never joined.

### 5.4 Data

1. **Time range:**
   - **Start** and **End** fields (`YYYY-MM-DD hh:mm:ss`).
   - A single **⏱ ▾** button opens a list of presets: Last 10 min · Last hour · Today · Yesterday · Last 7 days. Choosing one fills Start/End. "Today" and "Yesterday" use the displayed time zone.
   - UTC / local toggle; duration shown next to the fields.
   - **Coverage bar**:
     - zoom Week / Day / Hour, ◀ ▶ to move, mouse wheel to zoom;
     - drag to create a selection, drag the two handles to adjust Start/End, drag the middle to move the range;
     - colours: grey = on Shake only, green = downloaded, red = gap, blue = selection.
   - Start/End fields and the bar selection are **always synced both ways**.
   - Summary "N files to download" and a [Download & preview] button.
2. **Processing:**
   - Channels, band-pass filter, units (counts / m/s).
   - m/s is disabled while no response is available; reason in (?).
3. **Preview:** the three channels for the selected range.
4. **Export:**
   - Buttons [miniSEED] [CSV] [PNG] [PDF] [</> Code].
   - Code opens a panel with ObsPy code, a copy button and save as `.py`.
   - The code reads from the local SDS store, so it runs without the Shake.

### 5.5 Guide

The Manual as Markdown (English), bundled with the app and readable offline. Detail panels behind (?) can link to the matching Guide section.

### 5.6 ⚙ Settings

- **Per device:** display name, IP/hostname, SeedLink port, SSH user (default `myshake`), password (default `shakeme`, masked input, stored in the keyring), optional SSH key.
- [Test connection] tries an SSH login and reports the specific failure reason.
- Without a keyring backend, the app asks for the password once per session and never writes it to a file.
- **App-wide:** display time zone, data folder.

**[Set IP] button** (on the Status page):
- Lists wired interfaces to choose from and shows the exact command before running it.
- The OS asks for privileges, the app runs the command and re-checks immediately.
- Preferred behaviour: **let the OS pick a free link-local address**, so several laptops on one switch never clash.

| OS | Action | Prompt |
|---|---|---|
| Linux (NetworkManager) | `nmcli connection modify <conn> ipv4.link-local enabled` then `nmcli connection up <conn>` | polkit |
| Windows | Usually nothing to do (Windows self-assigns link-local). Otherwise `netsh interface ipv4 add address` | UAC |
| macOS | Usually nothing to do (macOS self-assigns link-local). Otherwise `networksetup` | macOS admin dialog |

## 6. Data flow

```
SeedLink ─► live.py ─► ring buffer ─► Live page
SFTP ─► archive.py ─► <data_dir>/sds/YYYY/AM/R77A7/EHZ.D/AM.R77A7.00.EHZ.D.YYYY.DOY
                                   └─► coverage.py ─► coverage bar
Selection ─► ObsPy SDS client ─► (response) ─► (filter) ─► export.py / codegen.py
```

- **Archive sync:**
  - Download missing days only.
  - **Today's** file is always re-downloaded.
  - Download to a temporary file, rename when complete.
- **The last few minutes** not yet in the Shake archive are filled from SeedLink.
- **Data folder** from `platformdirs`, e.g. `%LOCALAPPDATA%\rs3d` or `~/.local/share/rs3d`, containing `sds/`, `response/`, `logs/`, `config.toml` (devices, no passwords).

## 7. Error handling

The app never hangs or exits because of a connection problem. Every error becomes a `Check` with (?) help and is written to `logs/`.

| Situation | Handling |
|---|---|
| Cable unplugged / Shake powered off during Live | Reconnect after 2, 4, 8… s, at most 30 s apart; missing data left as a gap |
| Cable unplugged during download | Temporary file dropped; that file restarts next time; finished files kept |
| No link-local IP on the laptop | Laptop IP check errors + [Set IP]; dependent checks `skipped` |
| Wrong SSH credentials | SSH check errors; Live keeps working (SeedLink needs no password) |
| No archive on the Shake | Data page says "This Shake does not store data"; previously downloaded data still usable |
| Shake clock off | Warning on Status; Data page warns when the selection falls in a period with a bad clock |
| Gaps in the data | Red on the coverage bar; exports keep gaps, never fill values |
| No response available | m/s disabled; counts export still works |
| Several Shakes with the same mDNS name | Identified by SeedLink station code, not hostname |

## 8. Testing

- **`core/` – pytest, no device needed:**
  - a small miniSEED fixture recorded from R77A7;
  - fake SeedLink and SFTP servers running locally during tests;
  - simulated cable pulls and mid-transfer disconnects;
  - each [Set IP] command checked by recording the command, never executing it.
- **Device tests:** marked `@pytest.mark.device`, run only with a Shake connected.
- **`codegen`:** run the generated code and compare with the exported file; results must be identical.
- **CI:** GitHub Actions on Windows, macOS and Linux.
- **UI:** manual checklist in `docs/`.

## 9. Security

- Passwords only in the OS keyring; logs never contain passwords.
- Warning while the Shake still uses the default password.
- v1 sends no write command to the Shake.

## 10. Distribution

1. **v1:** Python package `rs3d-app`, run with `uvx rs3d-app`; opens in the browser at `http://127.0.0.1:<port>`.
2. **Later:** NiceGUI native mode + PyInstaller → `RS3D-App.exe` (Windows), `RS3D-App.app` (macOS), a Linux build, produced by GitHub Actions.

## 11. To verify on the device before building the affected modules

Needs SSH access to the Shake (`myshake`):

1. **Archive:**
   - does the Shake write to `/opt/data/archive`, and is the layout SDS;
   - size per day and retention.
   - If the Shake does **not** record: `archive.py` becomes a laptop-side recorder (SeedLink → SDS) while the app is open. The UI does not change.
2. **Response:** is there a response file on the Shake, and where.
   - If not: download StationXML from the Raspberry Shake FDSN service when the laptop has Internet, and cache it in `response/`.
3. **Data Forwarding:** which file on the Shake holds this setting.
4. **mDNS:** does the Shake advertise itself through Avahi, and under which name.

## 12. Later

- Vietnamese and Portuguese UI (`vi.yaml`, `pt.yaml`, language selector in Settings).
- USB GPS on the Shake.
- "Read + write" mode: change time server, toggle Data Forwarding, …
- PGA/PGV and summary metrics.
- Earthquake alerts (rsudp integration or in-app STA/LTA).
- Packaged executables (section 10.2).
