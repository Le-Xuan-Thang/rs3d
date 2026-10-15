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
    lines = text.strip().splitlines()
    if not lines:
        raise ValueError("empty date output")
    return float(lines[-1])


def utc_text(epoch: float) -> str:
    """'2027-01-15 08:00:00 UTC'."""
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


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


def diagnose(ntp: Check, offset: float | None, *, laptop_epoch: float | None = None) -> Check:
    """Refine the ntpq-only clock check with the Shake-versus-laptop offset (None: could not be measured).

    A laptop clock that is itself wrong makes the offset meaningless, so that is reported instead, with no fix.
    """
    if offset is None:
        return ntp
    if laptop_epoch is not None and not laptop_clock_ok(laptop_epoch):
        return Check("clock", Level.WARN, "this laptop's clock looks wrong (before 2025)", "clock.laptop")
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
    synced = False
    for _ in range(POLLS):
        sleep(POLL_SECONDS)
        try:
            synced = has_selected_source(shell.run(NTPQ_COMMAND))
        except ShellError:
            synced = False
        after = _measure(shell, now)
        if synced and after is not None and abs(after) <= T:
            return SyncResult("sync_now", before, after, True)
    if synced and after is not None:
        return SyncResult("sync_now", before, after, False,
                          f"ntpd found a time source, but the Shake still differs from this laptop by "
                          f"{abs(after):.0f} s. Check this laptop's clock before using Set from laptop.")
    return SyncResult("sync_now", before, after, False, "ntpd did not find a time source within 30 s")


def set_from_laptop(shell, now: Callable[[], float] = time.time,
                    sleep: Callable[[float], None] = time.sleep) -> SyncResult:
    """Set the Shake's clock to the laptop's UTC time, then let ntpd take over."""
    before = _measure(shell, now)
    if not laptop_clock_ok(now()):
        return SyncResult("set_from_laptop", before, None, False,
                          "The laptop clock looks wrong (before 2025), so it was not used.")
    try:
        shell.run(f"sudo -n date -u -s @{now():.3f}")  # fractional epoch, read as late as possible
        shell.run(RESTART_COMMAND)
    except ShellError as exc:
        return SyncResult("set_from_laptop", before, None, False, str(exc))
    after = None
    for _ in range(3):
        sleep(POLL_SECONDS)
        after = _measure(shell, now)
        if after is not None and abs(after) <= T:
            return SyncResult("set_from_laptop", before, after, True)
    return SyncResult("set_from_laptop", before, after, False, "The clock is still off after setting it.")


def log_sync(path: Path, result: SyncResult, now: Callable[[], float] = time.time) -> None:
    """Append one line per attempt. A log that cannot be written is not an error."""
    def num(v: float | None) -> str:
        return "?" if v is None else f"{v:+.2f}"

    stamp = datetime.fromtimestamp(now(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    message = " ".join(result.message.split())  # keep each attempt on one line
    status = "ok" if result.ok else f"FAILED: {message}"
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{stamp}\t{result.method}\tbefore={num(result.before)}\tafter={num(result.after)}\t{status}\n")
    except OSError:
        pass
