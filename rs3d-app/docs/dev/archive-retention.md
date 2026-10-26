# Archive retention (how many days of data to keep)

## What "7 days" and "30 days" mean here

The Raspberry Shake writes one miniSEED file per channel per day and deletes days older than its own retention
setting, `archkeep`. **RS3D does not delete anything itself**: the local store (`<data dir>/sds`) keeps every
file you download until you remove it.

So the number of days of data is decided in two places:

| Where | Setting | Who controls it |
|-------|---------|-----------------|
| On the Shake | `archkeep` in `/opt/settings/config/config.json` (key `other.archkeep`) | the Shake's web settings |
| In RS3D | `ARCHIVE_TARGET_DAYS` in `src/rs3d/core/status.py` | the code (this document) |

RS3D only **reads** `archkeep` (Status page, check "Archive"). It never writes it.

## What RS3D does with the target

`archive_check()` in `src/rs3d/core/status.py`:

- Shake keeps fewer days than `ARCHIVE_TARGET_DAYS` -> warning "keeps N days (target 30)", help id `archive.keep`.
- Days on the Shake that are not downloaded and are about to be deleted -> warning `archive.atrisk` (this one wins
  when both apply).
- `archkeep` missing or 0 (unknown) -> no comparison, no warning.

The texts live in `src/rs3d/help/en.toml` (`[help.archive]`, `[help.archive.keep]`).

## Changing the target

1. Edit `ARCHIVE_TARGET_DAYS` in `src/rs3d/core/status.py`.
2. Update the numbers written in the texts: `[help.archive]` and `[help.archive.keep]` in `src/rs3d/help/en.toml`
   ("30 days", "about 2.6 GB").
3. Update `tests/core/test_status.py` (`test_archive_warns_when_the_shake_keeps_fewer_than_the_target` and the 30 in
   `test_remote_days_and_archive_ok`).
4. Run `.venv/bin/python -m pytest -q`.

## Changing the retention on a Shake

RS3D cannot do this for you. Set the archive retention to the target in the Shake's web settings (the Shake's own
firmware owns this setting; menu names differ between firmware versions, so check yours), then reload the Status
page: the "Archive" line should say `keeps 30 days`.

Disk space: the archive takes about 85 MB per day (all three channels at 100 Hz), so 30 days is about 2.6 GB.
The Status page "Storage" line shows the free space; it warns below 10 % free. Make sure the SD card can hold the
target before raising it.

## Not done (ideas for a later change)

- A button that sets `archkeep` over SSH with sudo, like the clock fix in `src/rs3d/core/clock.py`. It needs a Shake
  to test against; the config file is JSON and the Shake services must pick up the change, so verify both on a real
  device first.
- A storage check that compares free space with `ARCHIVE_TARGET_DAYS` x 85 MB.
