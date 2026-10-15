# Changelog

All notable changes to this project are listed here, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Every change that a user of the RS3D app could notice gets a
line under **Unreleased** in the same commit or pull request that makes it.

## Unreleased

### Added
- Event alerts (rsudp-style STA/LTA trigger) on the vertical channel. Defaults: STA 6 s, LTA 30 s, on 3.95, reset 0.9,
  band-pass 0.8 to 9 Hz. All values are editable in Settings → Events.
- Live page: a banner while an event is in progress (red) and after it ends (orange, until dismissed), shading on the
  chart, and a list of the latest events.
- Detection starts when the app starts, without opening the Live page.
- Event log `events.jsonl` in the data folder. A corrupt line is skipped, and an unreadable log is never overwritten.
- Data page: downloaded or previewed days are scanned for events, a **Rescan** button re-runs detection with the current
  settings, and events are shaded on the preview.
- Helicorder: events are shaded on their rows.
- Status page: a warning when the event log cannot be written.
- Guide section "Events" and (?) help texts for every event setting.
- Status → Clock now compares the Shake's time with the laptop's, and says which one looks wrong.
- **Sync clock** button on the Status page: **Sync now** restarts the Shake's time service (laptop or Wi-Fi time source); **Set from laptop** copies the laptop's UTC time to the Shake. Every attempt is logged in `logs/clock-sync.log`.
- Status → Clock explains when the laptop's own clock looks wrong (before 2025), and offers no fix in that case.

### Changed
- Documentation: `docs/Manual.odt` regenerated; `data/` (downloaded miniSEED files) is now ignored by git.

### Notes
- The detector stays silent for the first LTA seconds after the app starts or after a gap in the data, so a shake in
  that time is not reported.
- Not yet tried against the real Shake: live banner, Data page scan and helicorder shading in a browser.
