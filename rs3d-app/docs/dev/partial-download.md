# Partial download of the Shake's archive (developer notes)

Before: **Download & preview** copied the whole day file of every selected channel (about 28 MB per channel per day).
Now it copies only the miniSEED records that cover Start-End.

## How

| File | What |
|------|------|
| `src/rs3d/core/miniseed_records.py` | reads record headers (start time, rate, length from blockette 1000), binary-searches a remote file, merges records |
| `src/rs3d/core/archive.py` | `plan_downloads` (what is missing), `download_range` (copy and merge), `sync_range` (all jobs) |
| `src/rs3d/core/fetched.py` | the ledger `fetched.json` in the SDS folder: spans of the archive that were already copied |
| `src/rs3d/core/coverage.py` | grey/red logic uses the ledger |
| `src/rs3d/app/pages/data.py` | the "To download: N · X MB" line and the call to `sync_range` |

1. `plan_downloads` lists, per channel and day on the Shake, the part of the selection that is neither in a local file
   (read from the record headers) nor in the ledger. Less than `TOLERANCE_S` (5 s) missing is ignored.
2. `download_range` opens the remote file over SFTP, finds the record length from the first record, binary-searches the
   time-ordered records for the range (4 records of padding on each side) and reads just that byte range.
3. The records are merged into the local day file (same record length required; one copy per start time, sorted) and
   written through a `.part` file. The ledger gets the span, clipped to where the Shake's file ends.
4. If the remote file is not a plain run of fixed-length records, or its record length differs from the local file's,
   the whole day file is copied (`download_day`) and the whole day is recorded in the ledger.

## Why a ledger

A partial day file cannot say "not copied yet" apart from "the Shake has nothing there". Without the ledger, a real
gap would look like missing data and be requested again on every download, and the strip would show it grey instead of
red. A day file with no ledger entry (other than the newest day on the Shake) is treated as a complete older copy.
Deleting `fetched.json` is safe: partial days then count as complete, so missing parts would not be requested; delete
the day file too if you want it fetched again.

## Limits

- Only tested against a fake Shake (a local folder behind the same `listdir/stat/open/get` calls). The first run on a
  real Shake is the real test.
- Binary search assumes the records are in time order. A file with out-of-order records (for example after a clock
  change) may lose a few records; copy the whole day by deleting the local day file and `fetched.json` entries.
- `BYTES_PER_SECOND` (330) is an estimate for 100 Hz Steim2 data used only for the size shown on the page.
- The live-helicorder preload (`core/preload.py`) still copies whole days.
