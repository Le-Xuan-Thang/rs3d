from datetime import date
from pathlib import Path

import pytest

from rs3d.core.clock import DATE_COMMAND
from rs3d.core.models import Check, Device, Level
from rs3d.core.seedlink import StationInfo
from rs3d.core.shell import ShellError
from rs3d.core.status import (
    ORDER, SHAKE_SCRIPT, archive_check, clock_check, forwarding_check, parse_sections,
    password_check, remote_days, run_checks, storage_check, wifi_check,
)

DATA = Path(__file__).parent.parent / "data"
REAL = (DATA / "shake_status.txt").read_text()  # captured from AM.R77A7 on 2026-10-12
DEVICE = Device(name="R77A7", host="169.254.221.62", station="R77A7")
STATION = StationInfo("AM", "R77A7", "00", ("EHZ", "EHN", "EHE"))
TODAY = date(2026, 10, 12)


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


def ok_ip():
    return Check("laptop_ip", Level.OK, "169.254.8.11 (enp2s0)", "laptop_ip")


def checks(**kw):
    args = dict(laptop_ip=ok_ip, probe_fn=lambda host, port: STATION,
                shell_factory=lambda dev, pw: FakeShell(), today=TODAY, now=lambda: NOW)
    args.update(kw)
    return {c.id: c for c in run_checks(DEVICE, "pw", **args)}


def test_parse_sections_of_real_output():
    s = parse_sections(REAL)
    assert set(s) == {"ntpq", "df", "archive", "config", "pwchanged", "wlan", "internet"}
    assert s["pwchanged"] == "yes"
    assert s["config"].startswith("{") and s["config"].endswith("}")


def test_all_checks_on_real_output():
    c = checks(local_days={date(2026, 10, 12)})
    assert [k for k in c] == list(ORDER)
    assert c["clock"].level is Level.OK and "ms via" in c["clock"].value
    assert c["internet"].value == "yes"
    assert c["wifi"].value == "10.10.178.153"
    assert c["storage"].level is Level.OK
    assert c["forwarding"].value == "OFF"
    assert c["password"].value == "changed"
    # 2025-09-25 (recorded with the wrong clock) is older than the 7-day retention
    assert c["archive"].level is Level.WARN and "keeps 7 days" in c["archive"].value


@pytest.mark.parametrize("date_output", ["garbage", ""])
def test_unusable_date_output_falls_back_to_ntpq(date_output):
    c = checks(shell_factory=lambda d, p: FakeShell(date=date_output))
    assert c["clock"].level is Level.OK and "ms via" in c["clock"].value


def test_wrong_laptop_clock_is_reported():
    old = 1_700_000_000.0
    c = checks(now=lambda: old, shell_factory=lambda d, p: FakeShell(date=f"{old:.9f}"))
    assert c["clock"].level is Level.WARN and c["clock"].help_id == "clock.laptop"
    assert c["clock"].action is None and "laptop" in c["clock"].value


def test_laptop_ip_error_skips_everything_else():
    bad = lambda: Check("laptop_ip", Level.ERROR, "no 169.254.x.x address", "laptop_ip", "set_ip")
    c = checks(laptop_ip=bad)
    assert c["laptop_ip"].level is Level.ERROR
    assert all(c[i].level is Level.SKIPPED for i in ORDER[1:])


def test_ssh_failure_skips_ssh_checks_but_not_seedlink():
    c = checks(shell_factory=lambda d, p: FakeShell(error=ShellError("auth", "wrong user name, password or key")))
    assert c["ssh"].level is Level.ERROR and c["ssh"].help_id == "ssh.auth"
    assert c["seedlink"].level is Level.OK and c["channels"].level is Level.OK
    assert all(c[i].level is Level.SKIPPED for i in ("clock", "storage", "archive", "password"))


def test_seedlink_failure():
    def boom(host, port):
        raise ConnectionRefusedError("refused")
    c = checks(probe_fn=boom)
    assert c["seedlink"].level is Level.ERROR and c["channels"].level is Level.SKIPPED


def test_garbled_section_becomes_unreadable_not_crash():
    c = checks(shell_factory=lambda d, p: FakeShell(REAL.replace("@@df", "@@dfx")))
    assert c["storage"].level is Level.ERROR and c["storage"].value == "could not read"


@pytest.mark.parametrize("line, level", [
    ("*81.193.254.213  150.214.94.5     2 u   10   64   37   12.638    0.753   1.342", Level.OK),
    ("*81.193.254.213  150.214.94.5     2 u   10   64   37   12.638  250.000   1.342", Level.WARN),
    ("*81.193.254.213  150.214.94.5     2 u   10   64   37   12.638 -1500.00   1.342", Level.ERROR),
    (" 81.193.254.213  150.214.94.5     2 u   10   64   37   12.638    0.753   1.342", Level.ERROR),
])
def test_clock_levels(line, level):
    assert clock_check("header\n=====\n" + line).level is level


def test_storage_warns_below_ten_percent():
    df = "Filesystem 1-blocks Used Available Capacity Mounted on\n/dev/root 1000 950 50 95% /"
    assert storage_check(df).level is Level.WARN


def test_remote_days_and_archive_ok():
    listing = "/x/EHZ.D/:\nAM.R77A7.00.EHZ.D.2026.284\nAM.R77A7.00.EHZ.D.2026.285"
    assert remote_days(listing) == {date(2026, 10, 11), date(2026, 10, 12)}
    c = archive_check(listing, {"other": {"archkeep": 7}}, set(), TODAY)
    assert c.level is Level.OK and c.value == "2026-10-11 → 2026-10-12 · keeps 7 days"


def test_archive_none():
    assert archive_check("", {}, set(), TODAY).help_id == "archive.none"


def test_forwarding_password_wifi():
    assert forwarding_check({"dataSharing": {"enabled": True}}).level is Level.WARN
    assert password_check("no").level is Level.WARN
    two = ("3: wlan0 inet 10.10.178.153/21 brd x\n3: wlan0 inet 10.10.176.119/21 brd x")
    assert wifi_check(two).level is Level.WARN and wifi_check(two).help_id == "wifi.duplicate"
    assert wifi_check("").value == "not used"


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
