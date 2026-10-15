# RS3D clock check and sync: design

Date: 2026-10-15. Status: draft for review. Branch `feat/rs3d-clock-sync` (stacked on `feat/rs3d-events`, MR !2).

## Goal

The Shake has no battery clock. After a power cut it restarts with an old time (on 2026-10-12 the data up to 15:55 UTC
carried the date 2025-09-25), and timestamps already written cannot be repaired. RS3D should notice a wrong Shake clock,
and let the user correct it with one click, either through the Shake's own Internet time sources (Wi-Fi) or from the
laptop's clock.

## Facts about the Shake (read-only probe, 2026-10-15)

- `ntpd` runs with `/etc/ntp.conf` containing `server 169.254.8.11 iburst prefer` (the laptop), three
  `*.debian.pool.ntp.org` servers and `tinker panic 0`. With `panic 0`, ntpd steps the clock at any offset instead of
  refusing, so a restart of `ntpd` corrects even a very wrong time as soon as one source is reachable.
- `sntp` and `timedatectl` exist. `ntpdate`, `chronyc` and `hwclock` do not. `ntpd` is not on the login PATH (it is
  managed by `systemctl`). The timezone is `Etc/UTC`.
- User `myshake` has passwordless `sudo`.

## Scope

In scope: detect a wrong Shake clock (compare with the laptop, and read ntpd's state), a **Sync now** action, a
**Set from laptop** fallback, a log of every correction, help text, Guide paragraph, changelog.

Out of scope: marking already-recorded data as unreliable, making the laptop serve NTP automatically, GPS time.

## 1. Detecting

- Each Status refresh runs `date -u +%s.%N` on the Shake as its own quick SSH command. The laptop notes `time.time()`
  before and after the call and takes the midpoint: `offset = shake_time - (t0 + t1) / 2` (positive: the Shake is ahead).
  The error is about half the round-trip time (tens of milliseconds).
- The existing `ntpq` reading stays. `synced` means `ntpq -pn` shows a selected source (a line starting with `*`).
- Result of the `clock` check (`diagnose(synced, offset)`; `T = 1.0` s, `BIG = 60` s):

| Shake has a selected source | `abs(offset)` | Level | Meaning | Fix button |
|---|---|---|---|---|
| yes | `<= T` | OK | as today (value shows ntpd offset and source) | none |
| yes | `> T` | WARN | the **laptop** clock probably differs; the Shake is synced | none |
| no | `> BIG` | ERROR | the Shake clock is wrong | Sync now |
| no | `T < abs <= BIG` | WARN | the Shake clock is off | Sync now |
| no | `<= T` | ERROR "no time source" | as today | Sync now |

- The value text shows both numbers, for example `Shake 3 s behind laptop · ntpd: no source`.
- If the quick `date` call fails, the check falls back to today's `ntpq`-only result.
- Sub-second accuracy stays with `ntpq`; this check exists to catch gross errors.

## 2. Fixing

Nothing on the Shake changes unless the user clicks and confirms. The dialog shows the Shake time, the laptop time and the
offset, and warns: "Changing the time can leave a small gap or overlap in the data."

- **Sync now** (`sync_now`): `sudo systemctl restart ntpd`, then poll every 2 s for up to 30 s until the Shake has a
  selected source and its offset against the laptop is within `T`. Success returns the new offset. If it does not settle,
  the dialog says so and offers **Set from laptop**.
- **Set from laptop** (`set_from_laptop`): refuses when the laptop UTC year is before 2025 (the laptop clock is itself
  wrong). Otherwise runs `sudo date -u -s @<laptop epoch>` then `sudo systemctl restart ntpd`, and re-measures.
- If `sudo` or `systemctl` fails, the dialog shows the Shake's error text. The app never retries on its own.
- Every attempt appends one line to `logs/clock-sync.log` in the data folder: UTC time, method, offset before, offset
  after (or the error). A failure to write the log is not fatal.

## 3. Structure

- `core/clock.py` (new, no UI imports): `parse_epoch(text) -> float`, `measure_offset(shell, now=time.time) -> float`,
  `diagnose(synced, offset) -> tuple[Level, str, str]` (level, value text, help id), `laptop_clock_ok(epoch) -> bool`,
  `sync_now(shell, now=time.time, sleep=time.sleep) -> SyncResult`, `set_from_laptop(shell, now=time.time,
  sleep=time.sleep) -> SyncResult`, `log_sync(path, result)`. `SyncResult` carries method, offset before, offset after, ok,
  message.
- `core/status.py`: the `clock` check uses `measure_offset` and `diagnose` and sets `action="sync_clock"` when a fix is
  possible. `Check.action` already exists (`set_ip`, `download`).
- `app/pages/status.py`: a button for `sync_clock` and a dialog in the style of the existing Set IP dialog, running the
  action in a worker thread (`run.io_bound`).
- `core/shell.py`: no code change; the module docstring stops saying "read-only use".
- Strings in `help/en.toml` (labels and help ids `clock.sync`, `clock.laptop`), Guide paragraph in `guide/en.md`, an entry
  in `CHANGELOG.md`.

## 4. Error handling

- SSH down: the check is `SKIPPED` as today; no button.
- Laptop clock obviously wrong (before 2025): the check explains it and offers no fix.
- A step in the middle of a recording may leave a gap or overlap in the Shake's data; the dialog says so before the click.
- `ntpd` already running with the wrong time and no reachable source (no cable to the laptop, no Wi-Fi): Sync now ends with
  "no time source reachable"; Set from laptop stays available.

## 5. Testing

- Pure tests: `parse_epoch`, midpoint offset with a fake clock, every row of the `diagnose` table including both
  thresholds exactly, `laptop_clock_ok`.
- Action tests with a fake shell that records commands and scripts replies: `sync_now` success after N polls, timeout,
  command failure; `set_from_laptop` runs the commands in order, refuses a bad laptop clock, re-measures; `log_sync` line
  format and a log-write failure that does not raise.
- `run_checks` with a fake shell: a wrong clock gives the new level and `action="sync_clock"`; a failing `date` call falls
  back to the old check.
- One check marked `device` (excluded by default) for the user to run by hand: set the Shake clock wrong with `sudo date`,
  press Sync now, expect recovery. It is not run by the agent.
