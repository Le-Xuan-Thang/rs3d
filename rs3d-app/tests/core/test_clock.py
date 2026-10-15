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
