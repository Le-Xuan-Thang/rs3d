"""Read-only health checks of the laptop link and the Shake -> list[Check] for the Status page."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Callable

from rs3d.core.models import Check, Device, Level
from rs3d.core.netcheck import check_laptop_ip
from rs3d.core.seedlink import StationInfo, probe
from rs3d.core.shell import Shell, ShellError

# One SSH round trip: every section starts with a line "@@name" (printed after a newline,
# because some files, e.g. config.json, do not end with one).
SHAKE_SCRIPT = r"""
printf '\n@@ntpq\n'; ntpq -pn 2>&1
printf '\n@@df\n'; df -P -B1 / 2>&1
printf '\n@@archive\n'; ls -1 /opt/data/archive/*/*/*/EHZ.D/ 2>/dev/null
printf '\n@@config\n'; cat /opt/settings/config/config.json 2>/dev/null
printf '\n@@pwchanged\n'; test -e /opt/settings/user/.pwchanged && echo yes || echo no
printf '\n@@wlan\n'; ip -4 -o addr show wlan0 2>/dev/null
printf '\n@@internet\n'; timeout 4 bash -c "</dev/tcp/1.1.1.1/443" 2>/dev/null && echo ok || echo fail
"""

ORDER = ("laptop_ip", "seedlink", "channels", "ssh", "clock", "internet", "wifi",
         "storage", "archive", "forwarding", "password")
SSH_DEPENDENT = ("clock", "internet", "wifi", "storage", "archive", "forwarding", "password")


def parse_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("@@"):
            current = line[2:].strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


# ---------------------------------------------------------------- individual checks (pure)

def clock_check(ntpq: str) -> Check:
    for line in ntpq.splitlines():
        if line.startswith("*"):
            fields = line[1:].split()
            remote, offset_ms = fields[0], float(fields[8])
            value = f"±{abs(offset_ms):.2f} ms via {remote}"
            if abs(offset_ms) > 1000:
                return Check("clock", Level.ERROR, value, "clock.offset")
            if abs(offset_ms) > 100:
                return Check("clock", Level.WARN, value, "clock.offset")
            return Check("clock", Level.OK, value, "clock")
    return Check("clock", Level.ERROR, "no time source", "clock.nosource")


def storage_check(df: str) -> Check:
    fields = df.splitlines()[-1].split()
    total, avail = int(fields[1]), int(fields[3])
    free = avail / total
    value = f"{avail / 1e9:.1f} GB free ({free:.0%})"
    return Check("storage", Level.WARN if free < 0.10 else Level.OK, value, "storage")


_DAY_FILE = re.compile(r"\.D\.(\d{4})\.(\d{3})$")


def remote_days(listing: str) -> set[date]:
    days = set()
    for name in listing.split():
        m = _DAY_FILE.search(name)
        if m:
            days.add(date(int(m[1]), 1, 1) + timedelta(days=int(m[2]) - 1))
    return days


def archive_check(listing: str, config: dict, local_days: set[date], today: date) -> Check:
    days = remote_days(listing)
    keep = int(config.get("other", {}).get("archkeep", 0) or 0)
    if not days:
        return Check("archive", Level.WARN, "no archive on the Shake", "archive.none")
    value = f"{min(days)} → {max(days)} · keeps {keep} days" if keep else f"{min(days)} → {max(days)}"
    at_risk = [d for d in days if d not in local_days and keep and (today - d).days >= keep - 1]
    if at_risk:
        return Check("archive", Level.WARN, value + f" · {len(at_risk)} day(s) about to be deleted",
                     "archive.atrisk", action="download")
    return Check("archive", Level.OK, value, "archive")


def forwarding_check(config: dict) -> Check:
    enabled = bool(config.get("dataSharing", {}).get("enabled", False))
    return Check("forwarding", Level.WARN if enabled else Level.OK, "ON" if enabled else "OFF", "forwarding")


def password_check(pwchanged: str) -> Check:
    changed = pwchanged.strip() == "yes"
    return Check("password", Level.OK if changed else Level.WARN,
                 "changed" if changed else "default", "password")


def internet_check(result: str) -> Check:
    ok = result.strip() == "ok"
    return Check("internet", Level.OK if ok else Level.WARN, "yes" if ok else "no", "internet")


def wifi_check(wlan: str) -> Check:
    ips = re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", wlan)
    if not ips:
        return Check("wifi", Level.OK, "not used", "wifi")
    if len(ips) > 1:
        return Check("wifi", Level.WARN, " + ".join(ips), "wifi.duplicate")
    return Check("wifi", Level.OK, ips[0], "wifi")


# ---------------------------------------------------------------- orchestration

def run_checks(
    device: Device,
    password: str | None,
    *,
    local_days: set[date] = frozenset(),
    today: date | None = None,
    laptop_ip: Callable[[], Check] = check_laptop_ip,
    probe_fn: Callable[[str, int], StationInfo] = probe,
    shell_factory: Callable[[Device, str | None], Shell] | None = None,
) -> list[Check]:
    """All checks in display order. Failed prerequisites turn dependent checks into SKIPPED."""
    today = today or date.today()
    results: dict[str, Check] = {}

    results["laptop_ip"] = laptop_ip()
    if results["laptop_ip"].level is Level.ERROR:
        return [results["laptop_ip"]] + [Check(i, Level.SKIPPED, "", i) for i in ORDER[1:]]

    try:
        info = probe_fn(device.host, device.seedlink_port)
        results["seedlink"] = Check("seedlink", Level.OK, f"{device.host}:{device.seedlink_port}", "seedlink")
        expected = {"EHZ", "EHN", "EHE"}
        missing = expected - set(info.channels)
        results["channels"] = Check("channels", Level.WARN if missing else Level.OK,
                                    " ".join(info.channels) or "none", "channels")
    except Exception as exc:
        results["seedlink"] = Check("seedlink", Level.ERROR, str(exc) or "unreachable", "seedlink")
        results["channels"] = Check("channels", Level.SKIPPED, "", "channels")

    try:
        if shell_factory is None:
            raise RuntimeError("no shell factory")
        with shell_factory(device, password) as sh:
            sections = parse_sections(sh.run(SHAKE_SCRIPT))
        results["ssh"] = Check("ssh", Level.OK, device.ssh_user, "ssh")
    except ShellError as exc:
        results["ssh"] = Check("ssh", Level.ERROR, str(exc), f"ssh.{exc.kind}")
        sections = None

    if sections is None:
        for i in SSH_DEPENDENT:
            results[i] = Check(i, Level.SKIPPED, "", i)
    else:
        try:
            config = json.loads(sections.get("config") or "{}")
        except json.JSONDecodeError:
            config = {}
        checks = {
            "clock": lambda: clock_check(sections.get("ntpq", "")),
            "internet": lambda: internet_check(sections.get("internet", "")),
            "wifi": lambda: wifi_check(sections.get("wlan", "")),
            "storage": lambda: storage_check(sections.get("df", "")),
            "archive": lambda: archive_check(sections.get("archive", ""), config, set(local_days), today),
            "forwarding": lambda: forwarding_check(config),
            "password": lambda: password_check(sections.get("pwchanged", "")),
        }
        for check_id, fn in checks.items():
            try:
                results[check_id] = fn()
            except Exception:  # unexpected output from the Shake must not break the page
                results[check_id] = Check(check_id, Level.ERROR, "could not read", "unreadable")

    return [results[i] for i in ORDER]
