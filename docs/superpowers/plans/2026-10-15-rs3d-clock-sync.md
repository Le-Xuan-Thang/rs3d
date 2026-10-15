# RS3D Clock Check and Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Status page notice a wrong Shake clock (after a power cut the Shake restarts with an old time) and let the user fix it with one confirmed click: restart ntpd (Wi-Fi/laptop time sources), or set the Shake's clock from the laptop.

**Architecture:** A UI-free `core/clock.py` holds the offset measurement, the diagnosis table and the two fix actions (they take any object with `run(cmd)`, so tests use a fake shell). `core/status.py` adds one quick `date -u` call and refines the existing `ntpq` clock check. The Status page gets a "Sync clock" button and a dialog in the style of the existing Set IP dialog. Every attempt is appended to `logs/clock-sync.log`.

**Tech Stack:** Python 3.11+, paramiko (existing `Shell`), NiceGUI, pytest. Run everything from `/home/thang/NCREP-RaspberryShake/rs3d-app` with `uv run pytest ...` (`python` is not on PATH).

**Spec:** `/home/thang/NCREP-RaspberryShake/docs/superpowers/specs/2026-10-15-rs3d-clock-sync-design.md`

## Global Constraints

- Thresholds: `T = 1.0` s (Shake and laptop may differ by this much), `BIG = 60` s (beyond this the Shake clock is plainly wrong), `MAX_RTT = 2.0` s (a slower SSH round trip is not trusted). Exactly `T` is fine; exactly `BIG` is still a warning.
- Offset sign: Shake time minus laptop time (positive: the Shake is ahead). Laptop time is read before and after the SSH call and the midpoint is used.
- Diagnosis table (`synced` = ntpd has a selected source, `ntp.help_id != "clock.nosource"`):
  - synced, `abs(offset) <= T`: unchanged OK. synced, `> T`: WARN, help `clock.laptop`, **no** action (the laptop clock probably differs); stays ERROR if the ntpq check was already ERROR.
  - not synced, `> BIG`: ERROR, help `clock.sync`, action `sync_clock`. `T < abs <= BIG`: WARN, help `clock.sync`, action `sync_clock`. `<= T`: the existing "no time source" ERROR with action `sync_clock`.
  - Offset could not be measured: the old ntpq-only result, unchanged.
- Nothing on the Shake changes without a click and a confirmation dialog that shows the times, and warns "Changing the time can leave a small gap or overlap in the Shake's data."
- **Sync now:** `sudo -n systemctl restart ntpd`, then poll every 2 s up to 30 s (15 polls) until a source is selected and the offset against the laptop is within `T`. **Set from laptop:** only after Sync now did not work; refuses if the laptop UTC is before 2025-01-01; runs `sudo -n date -u -s @<laptop epoch>` then `sudo -n systemctl restart ntpd`, then re-measures.
- Every attempt appends one tab-separated line to `logs/clock-sync.log` (UTC time, method, offset before, offset after, `ok` or `FAILED: <message>`). A log that cannot be written never raises.
- UI text goes through `app/strings.py` (`help/en.toml`). English first. Compact UI with (?) help icons.
- Every user-visible change gets a line in `CHANGELOG.md` under **Unreleased** (done in the last task).
- Commits: one commit per task, stage files explicitly (never `git add -A`), leave unrelated working-tree changes (`docs/Manual.odt`, `data/`) alone. Every commit message ends with:
  `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_012fJyELnPLTTW41WNCQKDPC`.

## Review Focus

Failure modes the spec implies but a first implementation would not test. Each has a pinning test in the task named.

1. **Slow or laggy SSH** (round trip over 2 s): the midpoint is no longer trustworthy and would raise false "clock off" warnings; the offset must be treated as unmeasured and the old ntpq-only result kept. Task 1 `test_measure_offset_rejects_a_slow_round_trip`, Task 2 `test_failing_date_falls_back_to_the_ntpq_check`.
2. **Shake ahead of the laptop** (negative and positive signs): wording must say "ahead of" or "behind" correctly. Task 1 `test_offset_text`.
3. **ntpd has a selected source but the clock stays off** after the restart (the source itself is wrong): Sync now must report failure after 30 s, not success. Task 1 `test_sync_now_fails_when_a_source_is_selected_but_the_clock_stays_off`.
4. **`sudo` asks for a password or `systemctl` fails**: the Shake's error text is shown, nothing is retried, the attempt is logged. Task 1 `test_sync_now_command_failure`, `test_set_from_laptop_command_failure`.
5. **The laptop clock is the wrong one**: when the Shake is synced to a time source and only the laptop disagrees, no fix button is offered; when the laptop year is before 2025, Set from laptop refuses and sends no `sudo` command. Task 1 `test_diagnose_synced_but_laptop_differs`, `test_set_from_laptop_refuses_bad_laptop_clock`; Task 2 `test_laptop_differs_but_shake_is_synced_gives_no_fix`.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/rs3d/core/clock.py` (new) | `SyncResult`, `measure_offset`, `diagnose`, `sync_now`, `set_from_laptop`, `log_sync` and small helpers. No UI imports. |
| `src/rs3d/core/status.py` | The `clock` check uses `measure_offset` and `diagnose`; new `now` parameter of `run_checks`. |
| `src/rs3d/app/pages/status.py` | "Sync clock" button and the dialog. |
| `src/rs3d/help/en.toml` | Labels and help texts. |
| `src/rs3d/core/shell.py` | Docstring only (no longer "read-only"). |
| `tests/core/test_clock.py` (new), `tests/core/test_status.py`, `tests/app/test_strings.py`, `tests/device/test_clock.py` (new) | Tests. |
| `src/rs3d/guide/en.md`, `../CHANGELOG.md` | Documentation. |

---

### Task 1: `core/clock.py`

**Files:**
- Create: `src/rs3d/core/clock.py`
- Test: `tests/core/test_clock.py`

**Interfaces:**
- Consumes: `rs3d.core.models.Check`, `Level`; `rs3d.core.shell.ShellError`; any object `shell` with `run(command: str) -> str` that raises `ShellError` on a non-zero exit.
- Produces:
  - Constants `T`, `BIG`, `MAX_RTT`, `MIN_LAPTOP_EPOCH`, `POLL_SECONDS`, `POLLS`, `DATE_COMMAND = "date -u +%s.%N"`, `NTPQ_COMMAND = "ntpq -pn"`, `RESTART_COMMAND = "sudo -n systemctl restart ntpd"`.
  - `SyncResult(method: str, before: float | None, after: float | None, ok: bool, message: str = "")` (frozen dataclass).
  - `parse_epoch(text) -> float`; `measure_offset(shell, now=time.time) -> float` (raises `ValueError` for bad output or a round trip over `MAX_RTT`, lets `ShellError` through); `has_selected_source(ntpq: str) -> bool`; `offset_text(offset: float) -> str`; `diagnose(ntp: Check, offset: float | None) -> Check`; `laptop_clock_ok(epoch: float) -> bool`.
  - `sync_now(shell, now=time.time, sleep=time.sleep) -> SyncResult`; `set_from_laptop(shell, now=time.time, sleep=time.sleep) -> SyncResult`; `log_sync(path, result, now=time.time) -> None`.

The code and tests below were prototyped in scratch and run green (24 tests).

- [ ] **Step 1: Write the failing tests**

Create `tests/core/test_clock.py`:

```python
import pytest

from rs3d.core.clock import (
    BIG, T, SyncResult, diagnose, has_selected_source, laptop_clock_ok, log_sync, measure_offset, offset_text,
    parse_epoch, set_from_laptop, sync_now,
)
from rs3d.core.models import Check, Level
from rs3d.core.shell import ShellError

NTP_OK = Check("clock", Level.OK, "±3.87 ms via 169.254.8.11", "clock")
NTP_NONE = Check("clock", Level.ERROR, "no time source", "clock.nosource")
NTP_BAD = Check("clock", Level.ERROR, "±2000.00 ms via x", "clock.offset")


class FakeClock:
    """Laptop time that advances 0.02 s per call; the Shake runs `skew` seconds ahead."""
    def __init__(self, start=1_800_000_000.0, skew=0.0):
        self.t, self.skew = start, skew

    def now(self):
        self.t += 0.02
        return self.t


class FakeShell:
    def __init__(self, clock, ntpq=("*x",), fail=None, steps=True):
        self.clock, self.ntpq, self.fail, self.commands = clock, list(ntpq), fail or {}, []
        self.steps = steps  # does restarting ntpd really correct the clock?

    def run(self, command):
        self.commands.append(command)
        for key, err in self.fail.items():
            if key in command:
                raise ShellError("command", err)
        if command.startswith("date -u +%s"):
            return f"{self.clock.t + self.clock.skew:.9f}\n"
        if command.startswith("ntpq"):
            return self.ntpq.pop(0) if len(self.ntpq) > 1 else self.ntpq[0]
        if command.startswith("sudo -n date -u -s @"):
            self.clock.skew = 0.0  # the Shake now has the laptop's time
        if "restart ntpd" in command and self.steps and self.ntpq[-1].startswith("*"):
            self.clock.skew = 0.0  # ntpd found a source and stepped the clock
        return ""


def test_parse_epoch():
    assert parse_epoch("1760544000.123456789\n") == pytest.approx(1760544000.123456789)
    with pytest.raises(ValueError):
        parse_epoch("not a number")


def test_measure_offset_uses_midpoint():
    clk = FakeClock(skew=5.0)
    sh = FakeShell(clk)
    assert measure_offset(sh, clk.now) == pytest.approx(5.0 - 0.01 + 0.0, abs=0.05)


def test_measure_offset_rejects_a_slow_round_trip():  # Review Focus 1
    class Slow(FakeShell):
        def run(self, command):
            self.clock.t += 5.0
            return super().run(command)

    clk = FakeClock()
    with pytest.raises(ValueError):
        measure_offset(Slow(clk), clk.now)


def test_has_selected_source():
    assert has_selected_source("     remote\n=====\n*169.254.8.11  x\n+other")
    assert not has_selected_source("     remote\n=====\n+169.254.8.11  x")


@pytest.mark.parametrize("off,text", [(3, "3 s ahead of the laptop"), (-3, "3 s behind the laptop"),
                                      (-300, "5 min behind the laptop"), (7200 * 2, "4 h ahead of the laptop"),
                                      (86400 * 400, "400 days ahead of the laptop")])
def test_offset_text(off, text):  # Review Focus 2
    assert offset_text(off) == text


def test_diagnose_synced_and_close_is_unchanged():
    assert diagnose(NTP_OK, 0.4) is NTP_OK
    assert diagnose(NTP_OK, T) is NTP_OK  # exactly T is fine


def test_diagnose_synced_but_laptop_differs():  # Review Focus 5
    c = diagnose(NTP_OK, 5.0)
    assert c.level is Level.WARN and c.help_id == "clock.laptop" and c.action is None and "5 s" in c.value
    assert diagnose(NTP_BAD, 5.0).level is Level.ERROR


def test_diagnose_not_synced_levels_and_thresholds():
    near = diagnose(NTP_NONE, 0.5)
    assert near.level is Level.ERROR and near.help_id == "clock.nosource" and near.action == "sync_clock"
    mid = diagnose(NTP_NONE, -(T + 0.01))
    assert mid.level is Level.WARN and mid.help_id == "clock.sync" and mid.action == "sync_clock"
    assert diagnose(NTP_NONE, BIG).level is Level.WARN  # exactly BIG is still a warning
    big = diagnose(NTP_NONE, BIG + 0.01)
    assert big.level is Level.ERROR and big.action == "sync_clock" and "behind" not in big.value and "ahead" in big.value


def test_diagnose_unmeasured_keeps_ntp_result():
    assert diagnose(NTP_NONE, None) is NTP_NONE


def test_laptop_clock_ok():
    assert laptop_clock_ok(1_800_000_000) and not laptop_clock_ok(1_700_000_000)


def test_sync_now_succeeds_after_polls():
    clk = FakeClock(skew=-400.0)
    sh = FakeShell(clk, ntpq=("remote\n", "remote\n", "*169.254.8.11 x"))
    res = sync_now(sh, clk.now, lambda s: None)
    assert res.ok and res.method == "sync_now" and res.before == pytest.approx(-400.0, abs=0.1)
    assert abs(res.after) <= T
    assert "sudo -n systemctl restart ntpd" in sh.commands


def test_sync_now_times_out_without_source():
    clk = FakeClock(skew=-400.0)
    sh = FakeShell(clk, ntpq=("remote\n",))
    sleeps = []
    res = sync_now(sh, clk.now, sleeps.append)
    assert not res.ok and "30 s" in res.message and len(sleeps) == 15 and res.after == pytest.approx(-400.0, abs=0.1)


def test_sync_now_fails_when_a_source_is_selected_but_the_clock_stays_off():  # Review Focus 3
    clk = FakeClock(skew=-400.0)
    sh = FakeShell(clk, ntpq=("*x",), steps=False)
    res = sync_now(sh, clk.now, lambda s: None)
    assert not res.ok and res.after == pytest.approx(-400.0, abs=0.1)


def test_sync_now_command_failure():  # Review Focus 4
    clk = FakeClock(skew=-400.0)
    sh = FakeShell(clk, fail={"systemctl": "sudo: a password is required"})
    res = sync_now(sh, clk.now, lambda s: None)
    assert not res.ok and "password" in res.message and res.after is None


def test_sync_now_survives_ntpq_error():
    clk = FakeClock(skew=0.0)
    sh = FakeShell(clk, fail={"ntpq": "ntpq: connection refused"})
    res = sync_now(sh, clk.now, lambda s: None)
    assert not res.ok


def test_set_from_laptop_runs_commands_in_order_and_remeasures():
    clk = FakeClock(skew=-90000.0)
    sh = FakeShell(clk)
    res = set_from_laptop(sh, clk.now, lambda s: None)
    cmds = [c for c in sh.commands if c.startswith("sudo")]
    assert cmds[0].startswith("sudo -n date -u -s @18") and cmds[1] == "sudo -n systemctl restart ntpd"
    assert res.ok and res.method == "set_from_laptop" and abs(res.after) <= T
    assert res.before == pytest.approx(-90000.0, abs=0.1)


def test_set_from_laptop_refuses_bad_laptop_clock():  # Review Focus 5
    clk = FakeClock(start=1_600_000_000.0, skew=100.0)
    sh = FakeShell(clk)
    res = set_from_laptop(sh, clk.now, lambda s: None)
    assert not res.ok and "laptop clock" in res.message
    assert not any(c.startswith("sudo") for c in sh.commands)


def test_set_from_laptop_command_failure():  # Review Focus 4
    clk = FakeClock(skew=100.0)
    sh = FakeShell(clk, fail={"date -u -s": "sudo: a password is required"})
    res = set_from_laptop(sh, clk.now, lambda s: None)
    assert not res.ok and "password" in res.message


def test_log_sync_appends_lines(tmp_path):
    p = tmp_path / "logs" / "clock-sync.log"
    log_sync(p, SyncResult("sync_now", -400.2, 0.03, True), lambda: 1_800_000_000.0)
    log_sync(p, SyncResult("set_from_laptop", None, None, False, "boom"), lambda: 1_800_000_060.0)
    lines = p.read_text().splitlines()
    assert lines[0] == "2027-01-15T08:00:00Z\tsync_now\tbefore=-400.20\tafter=+0.03\tok"
    assert lines[1].endswith("set_from_laptop\tbefore=?\tafter=?\tFAILED: boom")


def test_log_sync_failure_is_silent(tmp_path):
    blocker = tmp_path / "f"
    blocker.write_text("x")
    log_sync(blocker / "logs" / "x.log", SyncResult("sync_now", 0, 0, True))  # must not raise
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /home/thang/NCREP-RaspberryShake/rs3d-app && uv run pytest tests/core/test_clock.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'rs3d.core.clock'`.

- [ ] **Step 3: Implement**

Create `src/rs3d/core/clock.py`:

```python
"""Shake clock check and fix. The Shake has no battery clock, so after a power cut it restarts with an old time."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from rs3d.core.models import Check, Level
from rs3d.core.shell import ShellError

T = 1.0       # seconds: the Shake and the laptop may differ by this much
BIG = 60.0    # seconds: beyond this the Shake clock is plainly wrong
MIN_LAPTOP_EPOCH = 1735689600  # 2025-01-01 UTC: an earlier laptop clock is itself wrong
MAX_RTT = 2.0  # seconds: a slower SSH round trip makes the midpoint too uncertain to trust
POLL_SECONDS = 2.0
POLLS = 15    # 30 s in total

DATE_COMMAND = "date -u +%s.%N"
NTPQ_COMMAND = "ntpq -pn"
RESTART_COMMAND = "sudo -n systemctl restart ntpd"


@dataclass(frozen=True)
class SyncResult:
    method: str          # "sync_now" or "set_from_laptop"
    before: float | None  # offset (s) before the action, None if it could not be measured
    after: float | None
    ok: bool
    message: str = ""


def parse_epoch(text: str) -> float:
    return float(text.strip().splitlines()[-1])


def measure_offset(shell, now: Callable[[], float] = time.time) -> float:
    """Shake time minus laptop time in seconds (positive: the Shake is ahead).

    The laptop reads its clock before and after the SSH call and uses the midpoint, so the error is about half
    the round trip. A round trip slower than MAX_RTT raises ValueError (the offset would not be trustworthy).
    """
    t0 = now()
    out = shell.run(DATE_COMMAND)
    t1 = now()
    if t1 - t0 > MAX_RTT:
        raise ValueError(f"round trip of {t1 - t0:.1f} s is too slow to compare clocks")
    return parse_epoch(out) - (t0 + t1) / 2


def has_selected_source(ntpq: str) -> bool:
    return any(line.startswith("*") for line in ntpq.splitlines())


def offset_text(offset: float) -> str:
    """'3 s behind the laptop', '2 min ahead of the laptop'."""
    size = abs(offset)
    if size < 120:
        amount = f"{size:.0f} s"
    elif size < 7200:
        amount = f"{size / 60:.0f} min"
    elif size < 172800:
        amount = f"{size / 3600:.0f} h"
    else:
        amount = f"{size / 86400:.0f} days"
    return f"{amount} {'ahead of' if offset > 0 else 'behind'} the laptop"


def diagnose(ntp: Check, offset: float | None) -> Check:
    """Refine the ntpq-only clock check with the Shake-versus-laptop offset (None: could not be measured)."""
    if offset is None:
        return ntp
    synced = ntp.help_id != "clock.nosource"
    size = abs(offset)
    if synced:
        if size <= T:
            return ntp
        level = Level.ERROR if ntp.level is Level.ERROR else Level.WARN
        return Check("clock", level, f"laptop clock differs by {size:.0f} s · {ntp.value}", "clock.laptop")
    if size <= T:
        return replace(ntp, action="sync_clock")
    level = Level.ERROR if size > BIG else Level.WARN
    return Check("clock", level, f"Shake {offset_text(offset)} · ntpd: no source", "clock.sync",
                 action="sync_clock")


def laptop_clock_ok(epoch: float) -> bool:
    return epoch >= MIN_LAPTOP_EPOCH


def _measure(shell, now) -> float | None:
    try:
        return measure_offset(shell, now)
    except (ShellError, ValueError):
        return None


def sync_now(shell, now: Callable[[], float] = time.time,
             sleep: Callable[[float], None] = time.sleep) -> SyncResult:
    """Restart ntpd (it steps the clock at any offset: `tinker panic 0`) and wait for it to find a source."""
    before = _measure(shell, now)
    try:
        shell.run(RESTART_COMMAND)
    except ShellError as exc:
        return SyncResult("sync_now", before, None, False, str(exc))
    after = None
    for _ in range(POLLS):
        sleep(POLL_SECONDS)
        try:
            synced = has_selected_source(shell.run(NTPQ_COMMAND))
        except ShellError:
            synced = False
        after = _measure(shell, now)
        if synced and after is not None and abs(after) <= T:
            return SyncResult("sync_now", before, after, True)
    return SyncResult("sync_now", before, after, False, "ntpd did not find a time source within 30 s")


def set_from_laptop(shell, now: Callable[[], float] = time.time,
                    sleep: Callable[[float], None] = time.sleep) -> SyncResult:
    """Set the Shake's clock to the laptop's UTC time, then let ntpd take over."""
    before = _measure(shell, now)
    if not laptop_clock_ok(now()):
        return SyncResult("set_from_laptop", before, None, False,
                          "The laptop clock looks wrong (before 2025), so it was not used.")
    try:
        shell.run(f"sudo -n date -u -s @{int(now())}")
        shell.run(RESTART_COMMAND)
    except ShellError as exc:
        return SyncResult("set_from_laptop", before, None, False, str(exc))
    sleep(POLL_SECONDS)
    after = _measure(shell, now)
    ok = after is not None and abs(after) <= T
    return SyncResult("set_from_laptop", before, after, ok, "" if ok else "The clock is still off after setting it.")


def log_sync(path: Path, result: SyncResult, now: Callable[[], float] = time.time) -> None:
    """Append one line per attempt. A log that cannot be written is not an error."""
    def num(v: float | None) -> str:
        return "?" if v is None else f"{v:+.2f}"

    stamp = datetime.fromtimestamp(now(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    status = "ok" if result.ok else f"FAILED: {result.message}"
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{stamp}\t{result.method}\tbefore={num(result.before)}\tafter={num(result.after)}\t{status}\n")
    except OSError:
        pass
```

- [ ] **Step 4: Run to verify pass**

Run: `cd /home/thang/NCREP-RaspberryShake/rs3d-app && uv run pytest tests/core/test_clock.py -q`
Expected: 24 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/thang/NCREP-RaspberryShake
git add rs3d-app/src/rs3d/core/clock.py rs3d-app/tests/core/test_clock.py
git commit -m "feat: Shake clock offset, diagnosis and fix actions

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012fJyELnPLTTW41WNCQKDPC"
```

---

### Task 2: Use the offset in the Status checks

**Files:**
- Modify: `src/rs3d/core/status.py` (imports; `run_checks` signature, SSH block, `clock` lambda)
- Modify: `src/rs3d/core/shell.py` (module docstring only)
- Test: `tests/core/test_status.py`

**Interfaces:**
- Consumes: Task 1 (`diagnose`, `measure_offset`, `DATE_COMMAND`).
- Produces: `run_checks(..., now: Callable[[], float] = time.time)`; the `clock` check now carries `action="sync_clock"` when a fix is possible (Task 3 turns that into a button).

The existing `FakeShell` in `tests/core/test_status.py` asserts `command == SHAKE_SCRIPT`; it must also answer the new `date` command, and `checks()` must pass a fixed `now` so the existing tests keep an offset of 0.

- [ ] **Step 1: Update the fake and write the failing tests**

Edit `tests/core/test_status.py`:

1. Add `from rs3d.core.clock import DATE_COMMAND` before the line `from rs3d.core.models import Check, Device, Level`.

2. Replace the `FakeShell` class with:

```python
NOW = 1_800_000_000.0


class FakeShell:
    def __init__(self, output=REAL, error=None, date=f"{NOW:.9f}"):
        self.output, self.error, self.date = output, error, date

    def __enter__(self):
        if self.error:
            raise self.error
        return self

    def __exit__(self, *exc):
        return None

    def run(self, command):
        if command == DATE_COMMAND:
            if self.date is None:
                raise ShellError("command", "date failed")
            return self.date + "\n"
        assert command == SHAKE_SCRIPT
        return self.output
```

3. In `checks(**kw)`, change the `args = dict(...)` line to add `now=lambda: NOW`:

```python
    args = dict(laptop_ip=ok_ip, probe_fn=lambda host, port: STATION,
                shell_factory=lambda dev, pw: FakeShell(), today=TODAY, now=lambda: NOW)
```

4. Append at the end of the file:

```python
NO_SOURCE = REAL.replace("\n*", "\n+")  # the same ntpq output with no selected source


def test_clock_wrong_and_unsynced_offers_the_fix():
    c = checks(shell_factory=lambda dev, pw: FakeShell(output=NO_SOURCE, date=f"{NOW - 30:.9f}"))["clock"]
    assert c.level is Level.WARN and c.action == "sync_clock" and "behind the laptop" in c.value


def test_clock_year_off_is_an_error():
    c = checks(shell_factory=lambda dev, pw: FakeShell(output=NO_SOURCE, date=f"{NOW - 86400 * 400:.9f}"))["clock"]
    assert c.level is Level.ERROR and c.action == "sync_clock"


def test_laptop_differs_but_shake_is_synced_gives_no_fix():  # Review Focus 5
    c = checks(shell_factory=lambda dev, pw: FakeShell(date=f"{NOW + 30:.9f}"))["clock"]
    assert c.level is Level.WARN and c.action is None and c.help_id == "clock.laptop"


def test_failing_date_falls_back_to_the_ntpq_check():  # Review Focus 1
    c = checks(shell_factory=lambda dev, pw: FakeShell(date=None))["clock"]
    assert c.level is Level.OK and "ms via" in c.value
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /home/thang/NCREP-RaspberryShake/rs3d-app && uv run pytest tests/core/test_status.py -q`
Expected: failures such as `TypeError: run_checks() got an unexpected keyword argument 'now'`.

- [ ] **Step 3: Implement**

Edit `src/rs3d/core/status.py`:

1. In the imports, change `import re` to `import re` followed by `import time` (alphabetical: `json`, `re`, `time`), and add this line before `from rs3d.core.models import Check, Device, Level`:

```python
from rs3d.core.clock import diagnose, measure_offset
```

2. In the signature of `run_checks`, add after `shell_factory`:

```python
    now: Callable[[], float] = time.time,
```

3. Replace the SSH block

```python
        with shell_factory(device, password) as sh:
            sections = parse_sections(sh.run(SHAKE_SCRIPT))
        results["ssh"] = Check("ssh", Level.OK, device.ssh_user, "ssh")
```
with

```python
        with shell_factory(device, password) as sh:
            sections = parse_sections(sh.run(SHAKE_SCRIPT))
            try:
                offset = measure_offset(sh, now)
            except (ShellError, ValueError):  # the clock check then falls back to ntpq alone
                offset = None
        results["ssh"] = Check("ssh", Level.OK, device.ssh_user, "ssh")
```

4. Replace the `"clock"` entry of the `checks` dict with:

```python
            "clock": lambda: diagnose(clock_check(sections.get("ntpq", "")), offset),
```

Edit `src/rs3d/core/shell.py`: change the module docstring from `"""SSH/SFTP session to a Shake (paramiko). Read-only use in v1."""` to `"""SSH/SFTP session to a Shake (paramiko). The status checks only read; the clock fix runs sudo commands."""`.

- [ ] **Step 4: Run to verify pass**

Run: `cd /home/thang/NCREP-RaspberryShake/rs3d-app && uv run pytest tests/core -q`
Expected: all pass (the existing status tests still pass with offset 0).

- [ ] **Step 5: Commit**

```bash
cd /home/thang/NCREP-RaspberryShake
git add rs3d-app/src/rs3d/core/status.py rs3d-app/src/rs3d/core/shell.py rs3d-app/tests/core/test_status.py
git commit -m "feat: Clock check compares the Shake with the laptop

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012fJyELnPLTTW41WNCQKDPC"
```

---

### Task 3: Status page button, dialog and texts

**Files:**
- Modify: `src/rs3d/help/en.toml`
- Modify: `src/rs3d/app/pages/status.py`
- Test: `tests/app/test_strings.py` (append)

**Interfaces:**
- Consumes: Task 1 (`measure_offset`, `offset_text`, `sync_now`, `set_from_laptop`, `log_sync`, `SyncResult`), Task 2 (checks with `action="sync_clock"`), `AppState.shell(device)` (context manager with `.run`), `AppState.paths.logs`.
- Produces: label keys `action.sync_clock`, `clock.title`, `clock.offset`, `clock.working`, `clock.done`, `clock.failed`, `clock.sync_now`, `clock.set_laptop`, `clock.warning`; help ids `clock.sync`, `clock.laptop`; `sync_clock_dialog(state, device, after)` in `app/pages/status.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/app/test_strings.py` (reuse its imports; add `from rs3d.app.strings import help_text, label` if missing):

```python
def test_clock_sync_help_ids_have_short_and_detail():
    for hid in ("clock.sync", "clock.laptop"):
        short, detail = help_text(hid)
        assert short and detail, hid


def test_clock_sync_labels_exist():
    for key in ("action.sync_clock", "clock.title", "clock.offset", "clock.working", "clock.done",
                "clock.failed", "clock.sync_now", "clock.set_laptop", "clock.warning"):
        assert label(key) != key, key
```

(`label(key)` returns the key itself when missing, as `test_labels_and_fallback` shows.)

- [ ] **Step 2: Run to verify failure**

Run: `cd /home/thang/NCREP-RaspberryShake/rs3d-app && uv run pytest tests/app/test_strings.py -q`
Expected: the two new tests fail.

- [ ] **Step 3: Add the strings**

Edit `src/rs3d/help/en.toml`.

a. In `[labels.action]` add (after `set_ip = "Set IP"`):

```toml
sync_clock = "Sync clock"
```

b. After the `[labels.events]` table (before the `# ---- (?) texts` comment), add:

```toml
[labels.clock]
title = "Fix the Shake's clock"
offset = "Shake clock"
working = "Working… (up to 30 s)"
done = "Done. The Shake clock is now within 1 s of the laptop."
failed = "That did not work:"
sync_now = "Sync now"
set_laptop = "Set from laptop"
warning = "Changing the time can leave a small gap or overlap in the Shake's data. Sync now restarts the Shake's time service, which uses the laptop or the Internet. Set from laptop copies this laptop's clock to the Shake; use it only if this laptop's clock is right."
```

c. After the existing `[help.clock.nosource]` table add:

```toml
[help.clock.sync]
short = "The Shake clock is off and it has no time source."
detail = """
After a power cut the Shake starts with an old time (it has no battery clock) until its time service (**ntpd**) reaches a source.

Press **Sync clock**, then **Sync now**: the app restarts ntpd, which steps the clock from the laptop (`169.254.8.11`) or from Internet servers over Wi-Fi. If that does not work within 30 s, **Set from laptop** copies this laptop's UTC time to the Shake.

Data recorded while the clock was wrong keeps the wrong timestamps.
"""

[help.clock.laptop]
short = "The Shake is synced, but this laptop's clock differs from it."
detail = "The Shake has a selected time source, so its clock is probably right. Check this laptop's time (`timedatectl`) rather than changing the Shake."
```

- [ ] **Step 4: Implement the page**

Edit `src/rs3d/app/pages/status.py`.

1. Add to the imports (keep the existing ones):

```python
from rs3d.core.clock import log_sync, measure_offset, offset_text, set_from_laptop, sync_now
from rs3d.core.shell import ShellError
```

2. In `render()`, extend the action branch: after the `elif c.action == "download":` block add

```python
                        elif c.action == "sync_clock":
                            ui.button(label("action.sync_clock"),
                                      on_click=lambda: sync_clock_dialog(state, device, refresh)) \
                                .props("dense unelevated")
```

3. At the end of the file add:

```python
def sync_clock_dialog(state: AppState, device, after) -> None:
    log_path = state.paths.logs / "clock-sync.log"
    with ui.dialog() as dialog, ui.card().classes("min-w-96 max-w-xl"):
        ui.label(label("clock.title")).classes("text-base font-bold")
        info = ui.label("").classes("font-mono text-sm")
        ui.label(label("clock.warning")).classes("text-xs text-grey-7")
        result = ui.label("").classes("text-sm")
        with ui.row():
            sync = ui.button(label("clock.sync_now"), on_click=lambda: act(sync_now)).props("unelevated")
            laptop = ui.button(label("clock.set_laptop"), on_click=lambda: act(set_from_laptop)).props("flat")
            ui.button(label("action.close"), on_click=dialog.close).props("flat")
    laptop.set_visibility(False)  # offered only after Sync now did not work

    def work(action):
        with state.shell(device) as sh:
            return action(sh)

    async def act(action) -> None:
        sync.disable()
        laptop.disable()
        result.text = label("clock.working")
        try:
            res = await run.io_bound(work, action)
        except ShellError as exc:
            result.text = f"{label('clock.failed')} {exc}"
            return
        finally:
            sync.enable()
            laptop.enable()
        log_sync(log_path, res)
        result.text = label("clock.done") if res.ok else f"{label('clock.failed')} {res.message}"
        if not res.ok:
            laptop.set_visibility(True)
        await after()

    async def show() -> None:
        try:
            offset = await run.io_bound(work, measure_offset)
            info.text = f"{label('clock.offset')}: {offset_text(offset)}"
        except (ShellError, ValueError) as exc:
            info.text = str(exc)

    dialog.open()
    ui.timer(0.05, show, once=True)
```

- [ ] **Step 5: Run to verify pass**

Run: `cd /home/thang/NCREP-RaspberryShake/rs3d-app && uv run pytest -q`
Expected: all pass, including `tests/app/test_pages.py` (the Status page must still build).

- [ ] **Step 6: Commit**

```bash
cd /home/thang/NCREP-RaspberryShake
git add rs3d-app/src/rs3d/help/en.toml rs3d-app/src/rs3d/app/pages/status.py rs3d-app/tests/app/test_strings.py
git commit -m "feat: Sync clock button and dialog on the Status page

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012fJyELnPLTTW41WNCQKDPC"
```

---

### Task 4: Device test, Guide and CHANGELOG

**Files:**
- Create: `tests/device/test_clock.py`
- Modify: `src/rs3d/guide/en.md`
- Modify: `../CHANGELOG.md` (repo root: `/home/thang/NCREP-RaspberryShake/CHANGELOG.md`)

**Interfaces:** none (tests and text only).

- [ ] **Step 1: Device test (excluded by default; for the user to run by hand)**

Create `tests/device/test_clock.py`:

```python
"""Run with a Shake on the cable: RS3D_HOST=169.254.221.62 uv run pytest -m device tests/device/test_clock.py -v

The second test changes the Shake's clock on purpose, so it only runs when RS3D_TEST_BREAK_CLOCK=1 is set.
It restores the clock from the laptop at the end.
"""

import os
import time

import pytest

from rs3d.core.clock import T, measure_offset, set_from_laptop, sync_now
from rs3d.core.models import Device
from rs3d.core.shell import Shell

pytestmark = pytest.mark.device
HOST = os.environ.get("RS3D_HOST", "169.254.221.62")


@pytest.fixture
def shell(tmp_path):
    with Shell(Device(name="shake", host=HOST), None, tmp_path / "known_hosts") as sh:
        yield sh


def test_offset_is_small_on_a_synced_shake(shell):
    assert abs(measure_offset(shell)) < 5 * T


@pytest.mark.skipif(os.environ.get("RS3D_TEST_BREAK_CLOCK") != "1",
                    reason="set RS3D_TEST_BREAK_CLOCK=1 to change the Shake's clock on purpose")
def test_sync_now_recovers_a_wrong_clock(shell):
    shell.run(f"sudo -n date -u -s @{int(time.time()) - 3600}")
    try:
        assert abs(measure_offset(shell)) > 3000
        res = sync_now(shell)
        assert res.ok, res.message
    finally:
        if abs(measure_offset(shell)) > T:
            set_from_laptop(shell)
```

Run only the default suite to be sure nothing else changed: `cd /home/thang/NCREP-RaspberryShake/rs3d-app && uv run pytest -q` (the device tests are deselected by default).

- [ ] **Step 2: Guide**

Read `src/rs3d/guide/en.md` and the section `## 7. Clock`. Add this text at the end of that section (before `## Wi-Fi: two addresses`), in the guide's own tone:

```markdown
### When the clock is wrong

The Shake has no battery clock, so after a power cut it restarts with an old time until its time service (ntpd) reaches a source. Each time you open **Status**, RS3D also compares the Shake's time with this laptop's time. If the Shake is off and has no time source, the Clock row turns yellow or red and shows a **Sync clock** button.

1. Press **Sync clock**. The dialog shows how far the Shake is behind or ahead of the laptop.
2. Press **Sync now**. RS3D restarts the Shake's time service, which sets the clock from the laptop or from the Internet (Wi-Fi). It waits up to 30 seconds.
3. If that does not work, **Set from laptop** appears. It copies this laptop's UTC time to the Shake. Use it only when this laptop's clock is right.

Changing the time can leave a small gap or overlap in the data. Data recorded while the clock was wrong keeps its wrong timestamps. If the Shake has a time source and only this laptop disagrees, RS3D shows a warning and no button: check the laptop's clock instead. Every attempt is written to `logs/clock-sync.log` in the data folder.
```

- [ ] **Step 3: CHANGELOG**

In `/home/thang/NCREP-RaspberryShake/CHANGELOG.md`, under `## Unreleased` → `### Added`, add these lines at the end of that list:

```markdown
- Status → Clock now compares the Shake's time with the laptop's, and says which one looks wrong.
- **Sync clock** button on the Status page: **Sync now** restarts the Shake's time service (laptop or Wi-Fi time source); **Set from laptop** copies the laptop's UTC time to the Shake. Every attempt is logged in `logs/clock-sync.log`.
```

- [ ] **Step 4: Run the whole suite**

Run: `cd /home/thang/NCREP-RaspberryShake/rs3d-app && uv run pytest -q`
Expected: all pass (`test_guide_is_bundled` still passes).

- [ ] **Step 5: Commit**

```bash
cd /home/thang/NCREP-RaspberryShake
git add rs3d-app/tests/device/test_clock.py rs3d-app/src/rs3d/guide/en.md CHANGELOG.md
git commit -m "docs: guide, changelog and device test for the clock sync

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012fJyELnPLTTW41WNCQKDPC"
```

---

## Pending, needs the Shake on the cable

- Open Status and check the Clock row shows the right offset against the laptop (a few ms with a synced Shake).
- The dialog and both buttons in the browser.
- The guarded device test: `RS3D_TEST_BREAK_CLOCK=1 RS3D_HOST=169.254.221.62 uv run pytest -m device tests/device/test_clock.py -v` (it sets the Shake's clock one hour wrong, expects Sync now to fix it, and restores from the laptop at the end). Run it only when you are happy to disturb the Shake's clock for a minute.
